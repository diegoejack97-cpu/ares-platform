"""Configure synthetic identities/contracts only in an explicitly selected test DB."""

import os
from uuid import UUID

import psycopg


def seed(database_url: str) -> None:
    tenant = UUID("20000000-0000-0000-0000-000000000001")
    admin = UUID("10000000-0000-0000-0000-000000000001")
    with psycopg.connect(database_url) as db:
        for suffix, role in [
            (1, "admin"),
            (3, "manager"),
            (4, "seller"),
            (5, "auditor"),
        ]:
            user = UUID(f"10000000-0000-0000-0000-{suffix:012d}")
            db.execute(
                "insert into auth.users(id,email,email_confirmed_at) values(%s,%s,now()) "
                "on conflict(id) do nothing",
                (user, f"integration-{role}@example.invalid"),
            )
        db.execute(
            "insert into public.tenant_quotas(tenant_id,seats_limit,ai_daily_budget_brl,"
            "ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by,agent_slots,sentinel_slots) "
            "values(%s,10,5,50,5,'synthetic-test',%s,3,3) on conflict(tenant_id) do nothing",
            (tenant, admin),
        )
        for suffix, role in [
            (1, "admin"),
            (3, "manager"),
            (4, "seller"),
            (5, "auditor"),
        ]:
            db.execute(
                "insert into public.memberships(tenant_id,user_id,role) "
                "values(%s,%s,%s::public.membership_role) on conflict(tenant_id,user_id) do nothing",
                (tenant, UUID(f"10000000-0000-0000-0000-{suffix:012d}"), role),
            )
        db.execute(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) "
            "values(%s,'ares_connect','active',%s) on conflict(tenant_id,module) do nothing",
            (tenant, admin),
        )
        db.execute(
            "insert into public.tenant_billing_state(tenant_id,state,reason,changed_by) "
            "values(%s,'active','synthetic integration contract',%s) "
            "on conflict(tenant_id) do nothing",
            (tenant, admin),
        )


if __name__ == "__main__":
    url = os.environ.get("ARES_TEST_DATABASE_URL")
    if not url or os.environ.get("ARES_TEST_DATABASE_DISPOSABLE") != "1":
        raise SystemExit("Explicit disposable test database configuration is required")
    seed(url)
    print("Synthetic integration fixtures ready")
