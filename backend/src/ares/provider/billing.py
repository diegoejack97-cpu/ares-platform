from datetime import date
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import model_validator

from ares.provider.models import ProviderCommand, ProviderPrincipal
from ares.provider.service import FIELDS, ProviderConflict, ProviderMissing, ProviderService


class BillingCommand(ProviderCommand):
    expected_version: int
    state: Literal["active", "past_due", "degraded"]
    due_since: date | None = None
    grace_until: date | None = None

    @model_validator(mode="after")
    def dates(self) -> "BillingCommand":
        if self.expected_version < 1:
            raise ValueError("invalid_version")
        if self.state != "active" and (
            self.due_since is None or self.grace_until is None or self.grace_until < self.due_since
        ):
            raise ValueError("billing_dates_required")
        return self


def billing_status(database_url: str, tenant: UUID) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as db:
        return billing_status_on(db, tenant)


def billing_status_on(db: psycopg.Connection[Any], tenant: UUID) -> dict[str, Any]:
    row = db.execute(
        "select b.state,b.due_since,b.grace_until,"
        "(b.state='degraded' or (b.state='past_due' and "
        "(clock_timestamp() at time zone t.timezone)::date>b.grace_until)) as degraded "
        "from public.tenants t join public.tenant_billing_state b on b.tenant_id=t.id "
        "where t.id=%s",
        (tenant,),
    ).fetchone()
    return dict(row) if row else {"state": "unconfigured", "degraded": True}


def set_billing(
    service: ProviderService, actor: ProviderPrincipal, tenant: UUID, command: BillingCommand
) -> dict[str, Any]:
    with service.db() as db:
        service.authorize(db, actor)
        row = db.execute(
            "select version from public.tenants where id=%s for update", (tenant,)
        ).fetchone()
        if not row:
            raise ProviderMissing
        if row["version"] != command.expected_version:
            raise ProviderConflict("version_conflict", row["version"])
        before = db.execute(
            "select * from public.tenant_billing_state where tenant_id=%s", (tenant,)
        ).fetchone()
        if command.state == "degraded":
            today = db.execute(
                "select (now() at time zone timezone)::date today from public.tenants where id=%s",
                (tenant,),
            ).fetchone()
            assert today
            if command.grace_until is None or command.grace_until >= today["today"]:
                raise ProviderConflict("billing_grace_not_elapsed")
        after = db.execute(
            "insert into public.tenant_billing_state"
            "(tenant_id,state,due_since,grace_until,reason,changed_by) "
            "values(%s,%s,%s,%s,%s,%s) on conflict(tenant_id) do update set "
            "state=excluded.state,due_since=excluded.due_since,grace_until=excluded.grace_until,"
            "reason=excluded.reason,changed_by=excluded.changed_by,changed_at=now() returning *",
            (
                tenant,
                command.state,
                command.due_since,
                command.grace_until,
                command.reason,
                actor.user_id,
            ),
        ).fetchone()
        result = db.execute(
            "update public.tenants set version=version+1,updated_at=now() "
            f"where id=%s returning {FIELDS}",
            (tenant,),
        ).fetchone()
        service.audit(db, actor, tenant, "billing.set", command.reason, before, after)
        assert result
        return dict(result)
