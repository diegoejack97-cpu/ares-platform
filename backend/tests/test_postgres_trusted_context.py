"""Reference-SQL, access, cache, identity, freshness and context-scope acceptance."""
# ruff: noqa: E501

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import test_postgres_agents
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from ares.config import Settings
from ares.intelligence.context_api import context_router
from ares.intelligence.context_builder import ContextBuilder, ContextUnavailable
from ares.intelligence.queries import QueryIntent

fixture = test_postgres_agents.fixture
pytestmark = test_postgres_agents.pytestmark


@pytest.fixture
def context(fixture, monkeypatch):
    db, _, seed = fixture
    user, _ = seed()

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.intelligence.context_builder.psycopg.connect", connection)
    return db, user, ContextBuilder("synthetic fixture"), seed


def deal(db, user, value=10, currency="BRL", **kwargs):
    return db.execute(
        "insert into public.deals(tenant_id,title,value,currency,canonical_stage,external_stage,owner_user_id,connection_id,external_id,external_ref) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
        (
            user.tenant_id,
            kwargs.get("title", "Synthetic business"),
            value,
            currency,
            kwargs.get("stage", "proposal"),
            kwargs.get("stage", "proposal"),
            kwargs.get("owner"),
            kwargs.get("connection"),
            kwargs.get("external"),
            Jsonb(kwargs.get("ref")) if kwargs.get("ref") else None,
        ),
    ).fetchone()["id"]


def test_totals_are_complete_beyond_sample_and_preserve_zero_unknown_and_currency(context):
    db, user, builder, seed = context
    for _ in range(120):
        deal(db, user, 10)
    deal(db, user, 0)
    deal(db, user, None)
    deal(db, user, 7, "USD")
    deal(db, user, 3, None)
    other, _ = seed()
    deal(db, other, 999999)
    result = builder.build(user, QueryIntent())
    metrics = result["result"]["metrics"]
    reference = db.execute(
        "select count(*) total,sum(value) value from public.deals where tenant_id=%s and currency='BRL'",
        (user.tenant_id,),
    ).fetchone()
    brl = next(group for group in metrics["currencies"] if group["currency"] == "BRL")
    assert brl["records"] == reference["total"] == 122
    assert Decimal(brl["value"]) == reference["value"] == 1200
    assert brl["valued_records"] == 121
    assert metrics["total"] == 124 and metrics["missing_value"] == metrics["missing_currency"] == 1
    assert result["truncated"] and len(result["result"]["matches"]) <= 8
    assert (
        result["metadata"]["mirror_query_complete"] and not result["metadata"]["crm_sync_complete"]
    )
    assert result["tokens_upper_bound"] <= 2500


def test_cache_is_actor_tenant_purpose_intent_and_data_version_specific(context):
    db, user, builder, seed = context
    id_ = deal(db, user, 0)
    first = builder.build(user, QueryIntent())
    assert builder.build(user, QueryIntent())["context_ref"] == first["context_ref"]
    assert builder.build(user, QueryIntent(), purpose="chat")["context_ref"] != first["context_ref"]
    db.execute("update public.deals set value=35 where id=%s", (id_,))
    with pytest.raises(ContextUnavailable, match="context_stale"):
        builder.read(user, UUID(first["context_ref"]))
    fresh = builder.build(user, QueryIntent())
    assert fresh["context_ref"] != first["context_ref"]
    assert Decimal(fresh["result"]["metrics"]["currencies"][0]["value"]) == 35
    other, _ = seed()
    with pytest.raises(ContextUnavailable, match="context_not_found"):
        builder.read(other, UUID(fresh["context_ref"]))


def test_revocation_and_role_change_invalidate_even_claims_of_admin(context):
    db, user, builder, _ = context
    deal(db, user)
    first = builder.build(user, QueryIntent())
    db.execute(
        "update public.memberships set role='seller' where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    assert (
        builder.build(user.model_copy(update={"role": "admin"}), QueryIntent())["result"][
            "metrics"
        ]["total"]
        == 0
    )
    with pytest.raises(ContextUnavailable, match="context_stale"):
        builder.read(user, UUID(first["context_ref"]))
    db.execute(
        "update public.memberships set active=false where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    with pytest.raises(ContextUnavailable, match="context_access_denied"):
        builder.build(user, QueryIntent())


def test_seller_reads_only_owned_deals_and_owned_opportunities(context):
    db, user, builder, _ = context
    db.execute(
        "update public.memberships set role='seller' where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    deal(db, user, 10, owner=user.user_id)
    unassigned = deal(db, user, 20)
    deal(db, user, 999999)
    db.execute(
        "insert into public.ares_opportunities(tenant_id,deal_id,opportunity_type,state,owner_user_id) values(%s,%s,'revenue_recovery','prioritized',%s)",
        (user.tenant_id, unassigned, user.user_id),
    )
    result = builder.build(user, QueryIntent())
    assert result["result"]["metrics"]["total"] == 2
    assert result["metadata"]["scope"] == "own_portfolio"
    with pytest.raises(ContextUnavailable, match="context_scope_denied"):
        builder.build(user, QueryIntent(owner_id=uuid4()))


def test_same_external_id_on_two_connections_remains_two_businesses(context):
    db, user, builder, _ = context
    connections = [uuid4(), uuid4()]
    for conn in connections:
        db.execute(
            "insert into public.connections(id,tenant_id,provider,status) values(%s,%s,%s,'configured')",
            (conn, user.tenant_id, "synthetic-" + str(conn)),
        )
        deal(db, user, 15, connection=conn, external=f"{conn}:same-id", ref={"id": "same-id"})
    result = builder.build(user, QueryIntent())
    assert result["result"]["metrics"]["total"] == 2
    assert (
        len({item["source_ref"] for item in result["citations"] if item["kind"] == "record"}) == 2
    )
    assert (
        builder.build(user, QueryIntent(connection_id=connections[0]))["result"]["metrics"]["total"]
        == 1
    )
    db.execute("update public.connections set status='revoked' where id=%s", (connections[1],))
    assert builder.build(user, QueryIntent())["result"]["metrics"]["total"] == 1


def test_duplicate_identity_prefers_namespaced_record_and_declares_reconciliation(context):
    db, user, builder, _ = context
    conn = uuid4()
    db.execute(
        "insert into public.connections(id,tenant_id,provider,status) values(%s,%s,'synthetic','configured')",
        (conn, user.tenant_id),
    )
    deal(db, user, 999, connection=conn, external="same-id", ref={"id": "same-id"})
    native = deal(db, user, 5, connection=conn, external=f"{conn}:same-id", ref={"id": "same-id"})
    result = builder.build(user, QueryIntent())
    assert result["result"]["metrics"]["total"] == 1
    assert result["result"]["metrics"]["duplicate_rows"] == 1
    assert result["result"]["matches"][0]["id"] == str(native)
    db.execute(
        "update public.deals set external_stage='won',canonical_stage='won' where id=%s", (native,)
    )
    assert builder.build(user, QueryIntent(open_only=True))["result"]["metrics"]["total"] == 0
    db.execute(
        "update public.memberships set role='seller' where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    db.execute(
        "update public.deals set owner_user_id=%s where id<>%s and tenant_id=%s",
        (user.user_id, native, user.tenant_id),
    )
    assert builder.build(user, QueryIntent())["result"]["metrics"]["total"] == 0


def test_unknown_source_dates_and_sync_watermark_are_explicit(context):
    db, user, builder, _ = context
    deal(db, user)
    now = datetime.now(UTC)
    result = builder.build(user, QueryIntent(since=now - timedelta(days=1), until=now))
    assert result["result"]["metrics"]["total"] == 0
    assert result["result"]["metrics"]["excluded_unknown_dates"] == 1
    assert any("sem a data" in limitation for limitation in result["result"]["limitations"])


def test_chat_metrics_use_full_results_without_model_and_abort_revoked_context(context):
    from ares.chat.service import ChatService

    db, user, _, _ = context
    for _ in range(20):
        deal(db, user, 10)
    chat = ChatService(Settings(_env_file=None, openai_api_key=""))
    prepared = chat.prepare(user, None, "qual o total de negócios e valores?")
    stream = "".join(chat.stream(prepared))
    assert "20 negócios" in stream and "200,00" in stream and "event: done" in stream
    prepared = chat.prepare(user, None, "quantos negócios temos hoje?")
    db.execute(
        "update public.memberships set active=false where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    stream = "".join(chat.stream(prepared))
    assert "event: error" in stream and "20 negócios" not in stream


def test_period_filters_fields_and_empty_reference_do_not_expand_query(context):
    db, user, builder, _ = context
    old = deal(db, user, 100)
    deal(db, user, 20)
    db.execute("update public.deals set created_at=now()-interval '2 days' where id=%s", (old,))
    now = datetime.now(UTC)
    result = builder.build(
        user,
        QueryIntent(
            since=now - timedelta(days=1),
            until=now + timedelta(minutes=1),
            date_field="created",
            fields=["title"],
        ),
    )
    assert result["result"]["metrics"]["total"] == 1
    assert "value" not in result["result"]["matches"][0]
    assert result["result"]["metrics"]["changes"] == 0
    assert builder.build(user, QueryIntent(references=[]))["result"]["metrics"]["total"] == 0


def test_scope_readers_and_ttl_do_not_replace_intervention_snapshot(context):
    db, user, builder, _ = context
    opportunity = db.execute(
        "select id from public.ares_opportunities where tenant_id=%s limit 1", (user.tenant_id,)
    ).fetchone()["id"]
    intervention = db.execute(
        "select id,state_before_ref from public.ares_interventions where tenant_id=%s limit 1",
        (user.tenant_id,),
    ).fetchone()
    before = intervention["state_before_ref"]
    opp = builder.build(user, QueryIntent(entity="opportunity", scope_ref=opportunity))
    assert opp["result"]["details"]["opportunity"]["id"] == str(opportunity)
    result = builder.build(user, QueryIntent(entity="intervention", scope_ref=intervention["id"]))
    assert result["result"]["details"]["intervention"]["state_before_ref"] == str(before)
    rule = builder.build(user, QueryIntent(entity="sentinel", rule_id="SENTINEL-SLA-OVERDUE"))
    assert rule["result"]["details"]["kind"] == "sla_overdue"
    assert (
        db.execute(
            "select opportunity_id from public.context_snapshots where id=%s", (before,)
        ).fetchone()["opportunity_id"]
        == opportunity
    )
    db.execute(
        "update public.context_snapshots set valid_until=now()-interval '1 second' where id=%s",
        (UUID(result["context_ref"]),),
    )
    with pytest.raises(ContextUnavailable, match="context_stale"):
        builder.read(user, UUID(result["context_ref"]))


def test_http_intents_are_typed_authorized_and_noncacheable(context):
    _, user, _, _ = context
    server = FastAPI()
    server.include_router(context_router(Settings(_env_file=None), lambda: user))
    client = TestClient(server)
    response = client.post("/api/v1/context/query", json={})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/v1/context/" + response.json()["context_ref"]).status_code == 200
    assert client.post("/api/v1/context/query", json={"sql": "drop table deals"}).status_code == 422


def test_projected_citations_only_reference_projected_records(context):
    db, user, builder, _ = context
    for i in range(20):
        deal(db, user, title=f"{i} " + "ação " * 30)
    result = builder.build(user, QueryIntent(sample_limit=20))
    projected = json.loads(result["content"])
    ids = {item["id"] for item in projected["matches"]}
    assert result["metadata"]["cuts"]
    assert {item["record_id"] for item in result["citations"] if item["kind"] == "record"} == ids


def test_private_invalidation_trigger_preserves_cascading_tenant_deletion(context):
    db, _, _, _ = context
    row = db.execute(
        "select prosecdef,proconfig,has_function_privilege('authenticated',oid,'EXECUTE') allowed from pg_proc where oid='private.bump_context_data_version()'::regprocedure"
    ).fetchone()
    assert row["prosecdef"] and row["proconfig"] == ["search_path=pg_catalog"]
    assert not row["allowed"]
    tenant = uuid4()
    db.execute(
        "insert into public.tenants(id,name,slug) values(%s,'Synthetic cascade',%s)",
        (tenant, str(tenant)),
    )
    db.execute(
        "insert into public.deals(tenant_id,title) values(%s,'Synthetic cascade')", (tenant,)
    )
    # Existing commercial foreign keys deliberately prevent deleting live deals.
    db.execute("delete from public.deals where tenant_id=%s", (tenant,))
    db.execute("delete from public.sentinel_schedules where tenant_id=%s", (tenant,))
    db.execute("delete from public.tenants where id=%s", (tenant,))
    assert not db.execute(
        "select 1 from private.context_data_versions where tenant_id=%s", (tenant,)
    ).fetchone()
