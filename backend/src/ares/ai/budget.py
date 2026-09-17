from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ares.ai.quotas import QuotaDecision, QuotaGuard
from ares.provider.billing import billing_status


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    warning: bool
    daily_spend_usd: Decimal
    monthly_spend_usd: Decimal
    daily_limit_usd: Decimal
    monthly_limit_usd: Decimal


class AIBudgetGuard:
    """Pre-flight budget gate. It runs before any model invocation."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def reserve(self, tenant: UUID, run: UUID, estimate: Decimal) -> QuotaDecision:
        return QuotaGuard(self._database_url).reserve(tenant, run, estimate)

    def check(self, tenant_id: UUID, estimated_cost_usd: Decimal) -> BudgetDecision:
        if billing_status(self._database_url, tenant_id)["degraded"]:
            return BudgetDecision(False, True, Decimal(0), Decimal(0), Decimal(0), Decimal(0))
        if estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd must be non-negative")
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                select
                  limits.daily_limit_usd,
                  limits.monthly_limit_usd,
                  limits.warning_percent,
                  coalesce(sum(usage.cost_usd) filter (
                    where usage.occurred_at >= date_trunc('day', now())
                  ), 0) as daily_spend_usd,
                  coalesce(sum(usage.cost_usd) filter (
                    where usage.occurred_at >= date_trunc('month', now())
                  ), 0) as monthly_spend_usd
                from public.ai_budget_limits limits
                left join public.ai_usage_ledger usage
                  on usage.tenant_id = limits.tenant_id
                where limits.tenant_id = %s and limits.enabled
                group by limits.daily_limit_usd, limits.monthly_limit_usd,
                         limits.warning_percent
                """,
                (tenant_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("AI budget is not configured for tenant")
        daily_after = row["daily_spend_usd"] + estimated_cost_usd
        monthly_after = row["monthly_spend_usd"] + estimated_cost_usd
        allowed = (
            daily_after <= row["daily_limit_usd"] and monthly_after <= row["monthly_limit_usd"]
        )
        warning_ratio = Decimal(row["warning_percent"]) / Decimal(100)
        warning = (
            daily_after >= row["daily_limit_usd"] * warning_ratio
            or monthly_after >= row["monthly_limit_usd"] * warning_ratio
        )
        return BudgetDecision(
            allowed=allowed,
            warning=warning,
            daily_spend_usd=row["daily_spend_usd"],
            monthly_spend_usd=row["monthly_spend_usd"],
            daily_limit_usd=row["daily_limit_usd"],
            monthly_limit_usd=row["monthly_limit_usd"],
        )
