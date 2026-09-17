# SQL strings remain complete for review.
# ruff: noqa: E501
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    warning: bool
    code: str = "ok"


def estimate_usd(model: str, input_bytes: int, calls: int = 1) -> Decimal:
    if model not in {"gpt-5-mini", "gpt-5-mini-2025-08-07"}:
        raise ValueError("model_pricing_unconfigured")
    # Bytes upper-bound tokens; allowance covers instructions, JSON schema and tool envelope.
    return (
        (Decimal(input_bytes + 8192) * Decimal("0.25") + Decimal(900) * 2)
        * calls
        / Decimal(1_000_000)
    )


class QuotaGuard:
    def __init__(self, url: str):
        self.url = url

    def reserve(self, tenant: UUID, run: UUID, estimate: Decimal) -> QuotaDecision:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            return self.reserve_on(db, tenant, run, estimate)

    def reserve_on(
        self, db: psycopg.Connection[Any], tenant: UUID, run: UUID, estimate: Decimal
    ) -> QuotaDecision:
        if estimate < 0:
            raise ValueError("invalid_estimate")
        quota = db.execute(
            "select q.*, (now() at time zone t.timezone)::date as day from public.tenant_quotas q join public.tenants t on t.id=q.tenant_id where q.tenant_id=%s for update of q",
            (tenant,),
        ).fetchone()
        if not quota:
            return QuotaDecision(False, False, "quota_unconfigured")
        bill = db.execute(
            "select 1 from public.tenant_billing_state where tenant_id=%s and (state='degraded' or (state='past_due' and grace_until<%s))",
            (tenant, quota["day"]),
        ).fetchone()
        if bill:
            return QuotaDecision(False, False, "billing_degraded")
        prior = db.execute(
            "select status from public.ai_budget_reservations where tenant_id=%s and run_id=%s",
            (tenant, run),
        ).fetchone()
        if prior:
            return QuotaDecision(False, False, "run_already_reserved")
        month = quota["day"].replace(day=1)
        usage = db.execute(
            "select coalesce(sum(ai_spend_brl) filter(where day=%s),0) daily,coalesce(sum(ai_spend_brl),0) monthly from public.tenant_usage_daily where tenant_id=%s and day>=%s",
            (quota["day"], tenant, month),
        ).fetchone()
        pending = db.execute(
            "select coalesce(sum(reserved_brl) filter(where day=%s),0) daily,coalesce(sum(reserved_brl),0) monthly from public.ai_budget_reservations where tenant_id=%s and status='reserved'",
            (quota["day"], tenant),
        ).fetchone()
        assert usage and pending
        reserved = estimate * quota["usd_brl_rate"]
        daily = usage["daily"] + pending["daily"] + reserved
        monthly = usage["monthly"] + pending["monthly"] + reserved
        allowed = (
            daily <= quota["ai_daily_budget_brl"]
            and monthly <= quota["ai_monthly_budget_brl"]
            and quota["ai_daily_budget_brl"] > 0
        )
        warning = daily >= quota["ai_daily_budget_brl"] * Decimal("0.8") or monthly >= quota[
            "ai_monthly_budget_brl"
        ] * Decimal("0.8")
        db.execute(
            "insert into public.ai_budget_reservations(tenant_id,run_id,day,estimated_usd,usd_brl_rate,rate_source,reserved_brl,status) values(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                tenant,
                run,
                quota["day"],
                estimate,
                quota["usd_brl_rate"],
                quota["rate_source"],
                reserved,
                "reserved" if allowed else "denied",
            ),
        )
        return QuotaDecision(allowed, warning, "ok" if allowed else "ai_budget_exceeded")


def settle_on(
    db: psycopg.Connection[Any],
    tenant: UUID,
    run: UUID,
    cost: Decimal | None,
    not_called: bool = False,
) -> None:
    db.execute("select 1 from public.tenant_quotas where tenant_id=%s for update", (tenant,))
    # Unknown usage retains its reserve conservatively, including across period boundaries.
    if cost is None and not not_called:
        return
    row = db.execute(
        "update public.ai_budget_reservations set status=%s,actual_usd=%s,actual_brl=%s*usd_brl_rate,settled_at=now() where tenant_id=%s and run_id=%s and status='reserved' returning day,actual_brl",
        ("released" if not_called else "settled", cost, cost, tenant, run),
    ).fetchone()
    if row and not not_called:
        day, amount = (row["day"], row["actual_brl"]) if isinstance(row, dict) else row
        db.execute(
            "insert into public.tenant_usage_daily(tenant_id,day,ai_spend_brl,agent_runs) values(%s,%s,%s,1) on conflict(tenant_id,day) do update set ai_spend_brl=tenant_usage_daily.ai_spend_brl+excluded.ai_spend_brl,agent_runs=tenant_usage_daily.agent_runs+1",
            (tenant, day, amount),
        )
