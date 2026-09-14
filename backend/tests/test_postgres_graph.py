import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import test_postgres_agents
from psycopg.types.json import Jsonb

from ares.graph.projector import project_opportunity
from ares.graph.service import GraphService, GraphUnavailable

fixture = test_postgres_agents.fixture

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="PostgreSQL required"),
]


def test_graph_replay_traversal_tenant_fk_and_rls(fixture):
    db, _, seed = fixture
    # Validate pending migration in a rolled-back transaction before applying it.
    if db.execute("select to_regclass('public.graph_nodes') as name").fetchone()["name"] is None:
        db.execute(Path("supabase/migrations/20260914010000_m5_evidence_graph.sql").read_text())
    user, _ = seed()
    other, _ = seed()
    tenant = user.tenant_id
    opportunity = db.execute(
        "select id from public.ares_opportunities where tenant_id=%s", (tenant,)
    ).fetchone()["id"]
    deal, event = uuid4(), uuid4()
    db.execute(
        "insert into public.deals(id,tenant_id,title,external_id) "
        "values(%s,%s,'Grafo sintético',%s)",
        (deal, tenant, str(deal)),
    )
    db.execute("update public.ares_opportunities set deal_id=%s where tenant_id=%s", (deal, tenant))
    db.execute(
        "insert into public.commercial_events(id,tenant_id,event_type,producer,aggregate_type,"
        "aggregate_id,correlation_id,source,occurred_at,data,payload_hash) "
        "values(%s,%s,'deal.updated','test','deal',%s,%s,'ares',now(),%s,'test')",
        (
            event,
            tenant,
            str(deal),
            uuid4(),
            Jsonb({"company_id": "company-test", "contact_id": "contact-test"}),
        ),
    )
    db.execute(
        "insert into public.signals(tenant_id,event_id,opportunity_id,signal_type,"
        "rule_id,rule_version,severity,correlation_id) "
        "values(%s,%s,%s,'test','test','v1',1,%s)",
        (tenant, event, opportunity, uuid4()),
    )
    project_opportunity(db, tenant, opportunity)
    service = GraphService("")
    result = service.read_on(db, user, opportunity)
    assert len(result["nodes"]) == 4
    assert len(result["edges"]) == 3
    assert {e["evidence_event_id"] for e in result["edges"]} == {event}
    assert len(service.read_on(db, user, opportunity, 1)["edges"]) == 1
    project_opportunity(db, tenant, opportunity)
    again = service.read_on(db, user, opportunity)
    assert result["nodes"] == again["nodes"] and result["edges"] == again["edges"]
    # A late, older event must yield identical history to a fresh replay.
    late = uuid4()
    db.execute(
        "insert into public.commercial_events(id,tenant_id,event_type,producer,aggregate_type,"
        "aggregate_id,correlation_id,source,occurred_at,data,payload_hash) "
        "values(%s,%s,'deal.updated','test','deal',%s,%s,'ares',now()-interval '1 day',%s,'test')",
        (
            late,
            tenant,
            str(deal),
            uuid4(),
            Jsonb({"company_id": "company-test", "contact_id": "contact-test"}),
        ),
    )
    db.execute(
        "insert into public.signals(tenant_id,event_id,opportunity_id,signal_type,"
        "rule_id,rule_version,severity,correlation_id) "
        "values(%s,%s,%s,'test','test','v1',1,%s)",
        (tenant, late, opportunity, uuid4()),
    )
    project_opportunity(db, tenant, opportunity)
    history_sql = (
        "select * from public.graph_edges where tenant_id=%s "
        "order by src_id,dst_id,kind,evidence_event_id"
    )
    history = db.execute(history_sql, (tenant,)).fetchall()
    assert len(history) == 6
    assert sum(edge["valid_until"] is None for edge in history) == 3
    # Only isolated rollback fixture records are deleted here.
    db.execute("delete from public.graph_edges where tenant_id=%s", (tenant,))
    project_opportunity(db, tenant, opportunity)
    assert db.execute(history_sql, (tenant,)).fetchall() == history
    with pytest.raises(GraphUnavailable):
        service.read_on(db, other, opportunity)
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        db.execute(
            "insert into public.graph_edges(tenant_id,src_id,dst_id,kind,"
            "evidence_event_id,valid_from) values(%s,%s,%s,'concerns',%s,now())",
            (other.tenant_id, result["root_id"], result["nodes"][0]["id"], event),
        )
    db.execute(
        "select set_config('request.jwt.claims',%s::text,true)",
        (
            Jsonb(
                {
                    "sub": str(other.user_id),
                    "role": "authenticated",
                    "app_metadata": {"active_tenant_id": str(other.tenant_id)},
                }
            ),
        ),
    )
    db.execute("set local role authenticated")
    assert (
        db.execute(
            "select count(*) as n from public.graph_nodes where tenant_id=%s", (tenant,)
        ).fetchone()["n"]
        == 0
    )
    assert (
        db.execute(
            "select count(*) as n from public.graph_edges where tenant_id=%s", (tenant,)
        ).fetchone()["n"]
        == 0
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("delete from public.graph_edges")
    db.execute("reset role")
    db.execute(
        "select set_config('request.jwt.claims',%s::text,true)",
        (
            Jsonb(
                {
                    "sub": str(user.user_id),
                    "role": "authenticated",
                    "app_metadata": {"active_tenant_id": str(tenant)},
                }
            ),
        ),
    )
    db.execute("set local role authenticated")
    assert (
        db.execute(
            "select count(*) as n from public.graph_nodes where tenant_id=%s", (tenant,)
        ).fetchone()["n"]
        == 4
    )
    db.execute("reset role")
