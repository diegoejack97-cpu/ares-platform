"""M5 metrics on real PostgreSQL; isolated fixtures are always rolled back."""

import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.agents.service import AgentAccessDenied, AgentTransparencyService
from ares.auth.models import AuthenticatedUser

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="local PostgreSQL not configured"),
]


@pytest.fixture
def fixture():
    db = psycopg.connect(DATABASE_URL, row_factory=dict_row)

    class Service(AgentTransparencyService):
        @contextmanager
        def db(self):
            yield db

    def seed():
        tenant, actor, opportunity, snapshot, intervention = [uuid4() for _ in range(5)]
        db.execute("insert into auth.users(id) values(%s)", (actor,))
        db.execute(
            "insert into public.tenants(id,name,slug) values(%s,'M5 test',%s)",
            (tenant, str(tenant)),
        )
        db.execute(
            "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'manager')",
            (tenant, actor),
        )
        db.execute(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) "
            "values(%s,'ares_connect','active',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.ares_opportunities(id,tenant_id,opportunity_type,state) "
            "values(%s,%s,'revenue_recovery','prioritized')",
            (opportunity, tenant),
        )
        db.execute(
            "insert into public.context_snapshots(id,tenant_id,opportunity_id,"
            "snapshot_version,opportunity_state,content_hash,source) "
            "values(%s,%s,%s,1,'prioritized','test','ares')",
            (snapshot, tenant, opportunity),
        )
        db.execute(
            "insert into public.ares_interventions(id,tenant_id,opportunity_id,"
            "correlation_id,state_before_ref,source) values(%s,%s,%s,%s,%s,'ares')",
            (intervention, tenant, opportunity, uuid4(), snapshot),
        )
        account = AuthenticatedUser(user_id=actor, tenant_id=tenant, role="manager")

        def run(seconds, *, days=1, status="succeeded", mode="agno_openai"):
            start = datetime.now(UTC) - timedelta(days=days)
            end = start + timedelta(seconds=seconds) if seconds is not None else None
            db.execute(
                "insert into public.agent_runs(tenant_id,intervention_id,opportunity_id,"
                "context_ref,correlation_id,agent_name,agent_version,prompt_hash,"
                "output_schema_version,generation_mode,status,started_at,finished_at) "
                "values(%s,%s,%s,%s,%s,'follow-up+triage','m3.1','test',"
                "'recommendation.v1',%s,%s,%s,%s)",
                (tenant, intervention, opportunity, snapshot, uuid4(), mode, status, start, end),
            )

        return account, run

    try:
        yield db, Service(DATABASE_URL), seed
    finally:
        db.rollback()
        db.close()


def test_metrics_isolate_tenants_window_modes_and_unknown_cost(fixture):
    _, service, seed = fixture
    account, run = seed()
    other, other_run = seed()
    other_run(999)
    run(1)
    run(3)
    run(None, status="running")
    run(100, days=40)
    run(-1, status="failed")
    run(2, status="degraded", mode="deterministic_fallback")
    result = service.summary(account)
    assert len(result["items"]) == 2
    model, fallback = result["items"]
    assert model["runs"] == 4
    assert model["latency_samples"] == 2
    assert model["latency_p95_ms"] == pytest.approx(2900)
    assert model["running"] == 1
    assert model["failed"] == 1
    assert fallback["degraded"] == 1
    assert all(row["cost_usd"] is None for row in result["items"])
    assert service.summary(other)["items"][0]["runs"] == 1


def test_access_rechecked_for_expiry_membership_and_suspension(fixture):
    db, service, seed = fixture
    account, _ = seed()
    assert service.summary(account)["items"] == []
    for query in (
        "update public.tenant_entitlements set expires_at=now()-interval '1 day' "
        "where tenant_id=%s",
        "update public.memberships set active=false where tenant_id=%s",
        "update public.memberships set role='seller' where tenant_id=%s",
        "update public.tenants set status='suspended' where id=%s",
    ):
        db.execute("savepoint access_test")
        db.execute(query, (account.tenant_id,))
        with pytest.raises(AgentAccessDenied):
            service.summary(account)
        db.execute("rollback to savepoint access_test")
