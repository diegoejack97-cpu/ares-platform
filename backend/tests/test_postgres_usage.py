import os
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest
import test_postgres_agents

from ares.ai.usage import observe, record_usage_on

fixture = test_postgres_agents.fixture
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


def test_usage_ledger_idempotency_partial_totals_and_tenant_fk(fixture):
    db, service, seed = fixture
    user, run = seed()
    other, _ = seed()
    run(1)
    run_id = db.execute(
        "select id from public.agent_runs where tenant_id=%s", (user.tenant_id,)
    ).fetchone()["id"]
    usage = observe(
        SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_tokens=400), "gpt-5-mini"
    )
    record_usage_on(db, user.tenant_id, run_id, usage)
    record_usage_on(db, user.tenant_id, run_id, usage)
    ledger = db.execute(
        "select count(*) n,sum(cost_usd) cost from public.ai_usage_ledger where tenant_id=%s",
        (user.tenant_id,),
    ).fetchone()
    assert ledger["n"] == 1 and ledger["cost"] == Decimal("0.00056")
    item = service.summary(user)["items"][0]
    assert item["cost_status"] == "calculated"
    assert item["input_tokens"] == 1000 and item["cost_samples"] == 1
    run(2)
    item = service.summary(user)["items"][0]
    assert item["cost_status"] == "partial" and item["cost_usd"] == Decimal("0.00056")
    assert item["runs"] == 2 and item["usage_samples"] == 1
    assert service.summary(other)["items"] == []
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        record_usage_on(db, other.tenant_id, run_id, usage)
