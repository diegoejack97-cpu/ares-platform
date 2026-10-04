import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.ai.quotas import QuotaGuard, settle_on

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


@pytest.fixture
def contract():
    url = os.environ["ARES_TEST_DATABASE_URL"]
    tenant, actor = uuid4(), uuid4()
    with psycopg.connect(url) as db:
        db.execute("insert into auth.users(id) values(%s)", (actor,))
        db.execute(
            "insert into public.tenants(id,name,slug) values(%s,'Synthetic quota test',%s)",
            (tenant, str(tenant)),
        )
        db.execute(
            "insert into public.tenant_quotas(tenant_id,seats_limit,ai_daily_budget_brl,"
            "ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) "
            "values(%s,1,10,10,5,'synthetic test',%s)",
            (tenant, actor),
        )
    yield url, tenant, actor
    with psycopg.connect(url) as db:
        db.execute("delete from public.ai_budget_reservations where tenant_id=%s", (tenant,))
        db.execute("delete from public.tenant_usage_daily where tenant_id=%s", (tenant,))
        db.execute("delete from public.tenant_quotas where tenant_id=%s", (tenant,))
        db.execute("delete from public.sentinel_schedules where tenant_id=%s", (tenant,))
        db.execute("delete from public.tenants where id=%s", (tenant,))
        db.execute("delete from auth.users where id=%s", (actor,))


def test_concurrent_reservations_cannot_overspend(contract):
    url, tenant, _ = contract
    guard = QuotaGuard(url)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: guard.reserve(tenant, uuid4(), Decimal("1")), range(4)))
    assert sum(result.allowed for result in results) == 2
    assert any(result.warning for result in results if result.allowed)
    assert all(result.code == "ai_budget_exceeded" for result in results if not result.allowed)


def test_exchange_rate_is_frozen_and_settlement_idempotent(contract):
    url, tenant, _ = contract
    run = uuid4()
    assert QuotaGuard(url).reserve(tenant, run, Decimal("1.6")).warning
    with psycopg.connect(url, row_factory=dict_row) as db:
        db.execute("update public.tenant_quotas set usd_brl_rate=9 where tenant_id=%s", (tenant,))
        settle_on(db, tenant, run, Decimal("1"))
        settle_on(db, tenant, run, Decimal("1"))
        row = db.execute(
            "select actual_brl,usd_brl_rate from public.ai_budget_reservations where "
            "tenant_id=%s and run_id=%s",
            (tenant, run),
        ).fetchone()
        assert row["actual_brl"] == 5 and row["usd_brl_rate"] == 5
        usage = db.execute(
            "select ai_spend_brl,agent_runs from public.tenant_usage_daily where tenant_id=%s",
            (tenant,),
        ).fetchone()
        assert usage["ai_spend_brl"] == 5 and usage["agent_runs"] == 1


def test_unknown_cost_retains_reservation_and_not_called_releases(contract):
    url, tenant, _ = contract
    guard = QuotaGuard(url)
    run = uuid4()
    assert guard.reserve(tenant, run, Decimal("2")).allowed
    with psycopg.connect(url, row_factory=dict_row) as db:
        settle_on(db, tenant, run, None)
    assert not guard.reserve(tenant, uuid4(), Decimal(".01")).allowed
    with psycopg.connect(url, row_factory=dict_row) as db:
        settle_on(db, tenant, run, None, not_called=True)
    assert guard.reserve(tenant, uuid4(), Decimal("2")).allowed
    assert not guard.reserve(uuid4(), uuid4(), Decimal("1")).allowed


def test_membership_activation_enforces_seats_at_database(contract):
    url, tenant, actor = contract
    with psycopg.connect(url) as db:
        db.execute(
            "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'admin')",
            (tenant, actor),
        )
        other = uuid4()
        db.execute("insert into auth.users(id) values(%s)", (other,))
        db.execute(
            "insert into public.memberships(tenant_id,user_id,role,active) "
            "values(%s,%s,'seller',false)",
            (tenant, other),
        )
        with pytest.raises(psycopg.errors.RaiseException), db.transaction():
            db.execute(
                "update public.memberships set active=true where tenant_id=%s and user_id=%s",
                (tenant, other),
            )
        db.rollback()
