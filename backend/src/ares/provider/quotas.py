# ruff: noqa: E501
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from ares.provider.models import ProviderCommand, ProviderPrincipal
from ares.provider.service import FIELDS, ProviderConflict, ProviderMissing, ProviderService


class QuotaCommand(ProviderCommand):
    expected_version: int = Field(ge=1)
    seats_limit: int = Field(ge=0, le=100000)
    ai_daily_budget_brl: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    ai_monthly_budget_brl: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    usd_brl_rate: Decimal = Field(gt=0, max_digits=14, decimal_places=8)
    rate_source: str = Field(min_length=3, max_length=250)

    @model_validator(mode="after")
    def periods(self) -> "QuotaCommand":
        if self.ai_monthly_budget_brl < self.ai_daily_budget_brl:
            raise ValueError("monthly_below_daily")
        return self


def set_quota(
    service: ProviderService, actor: ProviderPrincipal, tenant: UUID, command: QuotaCommand
) -> dict[str, Any]:
    with service.db() as db:
        service.authorize(db, actor)
        current = db.execute(
            "select version from public.tenants where id=%s for update", (tenant,)
        ).fetchone()
        if not current:
            raise ProviderMissing
        if current["version"] != command.expected_version:
            raise ProviderConflict("version_conflict")
        occupied = db.execute(
            "select (select count(*) from public.memberships where tenant_id=%s and active)+(select count(*) from public.tenant_invitations where tenant_id=%s and status='pending') used",
            (tenant, tenant),
        ).fetchone()
        assert occupied
        if occupied["used"] > command.seats_limit:
            raise ProviderConflict("seats_below_occupied")
        previous = db.execute(
            "select * from public.tenant_quotas where tenant_id=%s for update", (tenant,)
        ).fetchone()
        updated = db.execute(
            "insert into public.tenant_quotas(tenant_id,seats_limit,ai_daily_budget_brl,ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) values(%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id) do update set seats_limit=excluded.seats_limit,ai_daily_budget_brl=excluded.ai_daily_budget_brl,ai_monthly_budget_brl=excluded.ai_monthly_budget_brl,usd_brl_rate=excluded.usd_brl_rate,rate_source=excluded.rate_source,updated_by=excluded.updated_by,updated_at=now() returning *",
            (
                tenant,
                command.seats_limit,
                command.ai_daily_budget_brl,
                command.ai_monthly_budget_brl,
                command.usd_brl_rate,
                command.rate_source,
                actor.user_id,
            ),
        ).fetchone()
        if previous is None:
            # Opening balance is valued at the explicitly supplied setup rate, never a fictional historical FX rate.
            db.execute(
                "insert into public.ai_budget_reservations(tenant_id,run_id,day,estimated_usd,usd_brl_rate,rate_source,reserved_brl,actual_usd,actual_brl,status,settled_at) select l.tenant_id,l.id,(l.occurred_at at time zone t.timezone)::date,l.cost_usd,%s,%s,l.cost_usd*%s,l.cost_usd,l.cost_usd*%s,'settled',now() from public.ai_usage_ledger l join public.tenants t on t.id=l.tenant_id where l.tenant_id=%s on conflict do nothing",
                (
                    command.usd_brl_rate,
                    "opening-balance: " + command.rate_source,
                    command.usd_brl_rate,
                    command.usd_brl_rate,
                    tenant,
                ),
            )
            db.execute(
                "insert into public.tenant_usage_daily(tenant_id,day,ai_spend_brl,agent_runs) select tenant_id,day,sum(actual_brl),count(*) from public.ai_budget_reservations where tenant_id=%s and status='settled' group by tenant_id,day on conflict(tenant_id,day) do nothing",
                (tenant,),
            )
        row = db.execute(
            f"update public.tenants set version=version+1,updated_at=now() where id=%s returning {FIELDS}",
            (tenant,),
        ).fetchone()
        service.audit(db, actor, tenant, "quota.set", command.reason, previous, updated)
        assert row
        return dict(row)
