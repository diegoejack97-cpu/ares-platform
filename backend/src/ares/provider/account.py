# SQL statements are kept intact for review.
# ruff: noqa: E501
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.integrations.service import IntegrationError
from ares.provider.licenses import (
    ActivateCommand,
    InviteCommand,
    LicensePage,
    LicenseService,
    MembershipCommand,
)


def account_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/account", tags=["M6 account"])
    dependency = Depends(require_user)
    service = LicenseService(settings.database_url)

    def run(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except IntegrationError as error:
            raise HTTPException(
                error.status, detail={"code": error.code, "correlation_id": error.correlation_id}
            ) from None
        except psycopg.errors.RaiseException:
            raise HTTPException(409, detail={"code": "seat_limit_exceeded"}) from None

    @router.get("/me")
    def current_account(user: AuthenticatedUser = dependency) -> dict[str, str]:
        """Expose the verified tenant role for navigation; authorization stays server-side."""
        with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
            tenant = db.execute(
                "select name from public.tenants where id=%s and status='active'",
                (user.tenant_id,),
            ).fetchone()
        if tenant is None:
            raise HTTPException(403, detail={"code": "tenant_inactive"})
        return {
            "tenant_id": str(user.tenant_id),
            "company_name": str(tenant["name"]),
            "role": user.role,
            "environment": settings.environment,
        }

    @router.get("/licenses", response_model=LicensePage)
    def listing(
        invitation_cursor: UUID | None = None,
        member_cursor: UUID | None = None,
        user: AuthenticatedUser = dependency,
    ) -> Any:
        return run(lambda: service.listing(user, invitation_cursor, member_cursor))

    @router.post("/invitations")
    def invite(command: InviteCommand, user: AuthenticatedUser = dependency) -> Any:
        return run(lambda: service.invite(user, command))

    @router.post("/invitations/{id}/activate")
    def activate(id: UUID, command: ActivateCommand, user: AuthenticatedUser = dependency) -> Any:
        return run(lambda: service.activate(user, id, command))

    @router.post("/invitations/{id}/cancel")
    def cancel(id: UUID, command: MembershipCommand, user: AuthenticatedUser = dependency) -> Any:
        return run(lambda: service.cancel(user, id, command))

    @router.post("/memberships/{id}")
    def member(id: UUID, command: MembershipCommand, user: AuthenticatedUser = dependency) -> Any:
        return run(lambda: service.membership(user, id, command))

    @router.get("/quota")
    def quota(user: AuthenticatedUser = dependency) -> Any:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
            row = db.execute(
                "select q.ai_daily_budget_brl,q.ai_monthly_budget_brl,q.usd_brl_rate,q.rate_source,q.updated_at,(now() at time zone t.timezone)::date as day from public.tenant_quotas q join public.tenants t on t.id=q.tenant_id where q.tenant_id=%s",
                (user.tenant_id,),
            ).fetchone()
            if not row:
                return {"configured": False}
            usage = db.execute(
                "select coalesce(sum(ai_spend_brl) filter(where day=%s),0) daily,coalesce(sum(ai_spend_brl),0) monthly from public.tenant_usage_daily where tenant_id=%s and day>=%s",
                (row["day"], user.tenant_id, row["day"].replace(day=1)),
            ).fetchone()
            pending = db.execute(
                "select coalesce(sum(reserved_brl) filter(where day=%s),0) daily_reserved, "
                "coalesce(sum(reserved_brl),0) reserved from public.ai_budget_reservations "
                "where tenant_id=%s and status='reserved'",
                (row["day"], user.tenant_id),
            ).fetchone()
            assert usage and pending
            return {
                "configured": True,
                **row,
                **usage,
                **pending,
                "daily_available": max(
                    Decimal(0),
                    row["ai_daily_budget_brl"] - usage["daily"] - pending["daily_reserved"],
                ),
                "monthly_available": max(
                    Decimal(0),
                    row["ai_monthly_budget_brl"] - usage["monthly"] - pending["reserved"],
                ),
                "warning": usage["daily"] + pending["daily_reserved"]
                >= row["ai_daily_budget_brl"] * Decimal("0.8")
                or usage["monthly"] + pending["reserved"]
                >= row["ai_monthly_budget_brl"] * Decimal("0.8"),
            }

    return router
