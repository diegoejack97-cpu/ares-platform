import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from ares.sentinels.service import RULE_ID, SentinelService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("ARES_TEST_DATABASE_URL"), reason="isolated PostgreSQL required"
    ),
]


def test_sentinel_drains_backlog_before_next_daily_slot():
    url = os.environ["ARES_TEST_DATABASE_URL"]
    tenant, deal = uuid4(), uuid4()
    actor = UUID("10000000-0000-0000-0000-000000000001")
    with psycopg.connect(url) as db:
        db.execute(
            "insert into public.tenants(id,name,slug,timezone) "
            "values(%s,'Synthetic backlog',%s,'UTC')",
            (tenant, str(tenant)),
        )
        db.execute(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) "
            "values(%s,'ares_connect','active',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.tenant_quotas(tenant_id,seats_limit,sentinel_slots,"
            "ai_daily_budget_brl,ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) "
            "values(%s,1,1,0,0,1,'synthetic test',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.deals(id,tenant_id,title) values(%s,%s,'Synthetic backlog deal')",
            (deal, tenant),
        )
        for index in range(71):
            db.execute(
                "insert into public.ares_opportunities(tenant_id,deal_id,"
                "opportunity_type,state,sla_at) values(%s,%s,%s,'detected','2000-01-01')",
                (tenant, deal, f"synthetic_backlog_{index}"),
            )
        slot = (datetime.now(UTC) + timedelta(hours=1)).time().replace(tzinfo=None)
        db.execute(
            "update public.sentinel_schedules set enabled=true,interval_minutes=1440,"
            "start_time_local=%s,next_run_at='1900-01-01' where tenant_id=%s and rule_id=%s",
            (slot, tenant, RULE_ID),
        )
    try:
        service = SentinelService(url)
        for iteration in range(15):
            service.scan_sync()
            with psycopg.connect(url) as db:
                count = db.execute(
                    "select count(*) from public.sentinel_findings where tenant_id=%s", (tenant,)
                ).fetchone()[0]
                next_run = db.execute(
                    "select next_run_at from public.sentinel_schedules "
                    "where tenant_id=%s and rule_id=%s",
                    (tenant, RULE_ID),
                ).fetchone()[0]
                if iteration == 0:
                    assert 0 < count <= 50
                    assert next_run < datetime.now(UTC) + timedelta(seconds=15)
                if count == 71:
                    break
                db.execute(
                    "update public.sentinel_schedules set next_run_at='1900-01-01' "
                    "where tenant_id=%s and rule_id=%s",
                    (tenant, RULE_ID),
                )
        assert count == 71
        # All work fits across bounded batches; the normal schedule resumes afterwards.
        service.scan_sync()
        with psycopg.connect(url) as db:
            assert db.execute(
                "select count(*) from public.sentinel_findings where tenant_id=%s", (tenant,)
            ).fetchone() == (71,)
    finally:
        with psycopg.connect(url) as db:
            for table in (
                "sentinel_findings",
                "sentinel_scan_runs",
                "sentinel_schedules",
                "ares_opportunities",
                "deals",
                "tenant_entitlements",
                "tenant_quotas",
            ):
                from psycopg import sql

                db.execute(
                    sql.SQL("delete from public.{} where tenant_id=%s").format(
                        sql.Identifier(table)
                    ),
                    (tenant,),
                )
            db.execute("delete from public.tenants where id=%s", (tenant,))
