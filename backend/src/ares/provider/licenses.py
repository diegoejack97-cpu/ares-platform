# ruff: noqa: E501
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from ares.auth.models import AuthenticatedUser
from ares.integrations.service import IntegrationError
from ares.leads.models import LeadInput


class InviteCommand(BaseModel):
    email: str = Field(max_length=254)
    role: Literal["admin", "manager", "seller", "auditor"]
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("email")
    @classmethod
    def normalized(cls, value: str) -> str:
        result = LeadInput.email_value(value.strip())
        if not result:
            raise ValueError("email_required")
        return result


class ActivateCommand(BaseModel):
    user_id: UUID
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class MembershipCommand(BaseModel):
    expected_version: int = Field(ge=1)
    active: bool
    reason: str = Field(min_length=3, max_length=500)


class InvitationRecord(BaseModel):
    id: UUID
    email: str
    role: str
    status: str
    version: int


class MembershipRecord(BaseModel):
    user_id: UUID
    email: str | None = None
    role: str
    active: bool
    version: int


class LicensePage(BaseModel):
    seats_limit: int
    used: int
    invitations: list[InvitationRecord]
    memberships: list[MembershipRecord]
    next_invitation: UUID | None
    next_member: UUID | None


class LicenseService:
    def __init__(self, url: str):
        self.url = url

    def authorize(self, db: psycopg.Connection[Any], user: AuthenticatedUser) -> dict[str, Any]:
        if (
            user.role != "admin"
            or not db.execute(
                "select 1 from public.memberships where tenant_id=%s and user_id=%s and role='admin' and active",
                (user.tenant_id, user.user_id),
            ).fetchone()
        ):
            raise IntegrationError("admin_required", 403)
        db.execute("select 1 from public.tenants where id=%s for update", (user.tenant_id,))
        quota = db.execute(
            "select seats_limit from public.tenant_quotas where tenant_id=%s", (user.tenant_id,)
        ).fetchone()
        if not quota:
            raise IntegrationError("seat_contract_unconfigured", 409)
        return dict(quota)

    def used(self, db: psycopg.Connection[Any], tenant: UUID) -> int:
        row = db.execute(
            "select (select count(*) from public.memberships where tenant_id=%s and active)+(select count(*) from public.tenant_invitations where tenant_id=%s and status='pending') used",
            (tenant, tenant),
        ).fetchone()
        assert row
        return int(row["used"])

    def audit(
        self,
        db: psycopg.Connection[Any],
        user: AuthenticatedUser,
        action: str,
        reason: str,
        id: UUID,
    ) -> None:
        db.execute(
            "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'human',%s,%s,%s,'ares:licenses',%s)",
            (
                user.tenant_id,
                user.user_id,
                action,
                uuid4(),
                Jsonb({"target_id": str(id), "reason": reason}),
            ),
        )

    def listing(
        self,
        user: AuthenticatedUser,
        invitation_cursor: UUID | None = None,
        member_cursor: UUID | None = None,
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            quota = self.authorize(db, user)
            invitations = db.execute(
                "select id,email,role,status,version from public.tenant_invitations where tenant_id=%s and (%s::uuid is null or id>%s) order by id limit 51",
                (user.tenant_id, invitation_cursor, invitation_cursor),
            ).fetchall()
            members = db.execute(
                "select m.user_id,u.email,m.role,m.active,m.version from public.memberships m left join auth.users u on u.id=m.user_id where m.tenant_id=%s and (%s::uuid is null or m.user_id>%s) order by m.user_id limit 51",
                (user.tenant_id, member_cursor, member_cursor),
            ).fetchall()
            return {
                "seats_limit": quota["seats_limit"],
                "used": self.used(db, user.tenant_id),
                "invitations": invitations[:50],
                "memberships": members[:50],
                "next_invitation": invitations[49]["id"] if len(invitations) > 50 else None,
                "next_member": members[49]["user_id"] if len(members) > 50 else None,
            }

    def invite(self, user: AuthenticatedUser, command: InviteCommand) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            quota = self.authorize(db, user)
            used = self.used(db, user.tenant_id)
            if used >= quota["seats_limit"]:
                raise IntegrationError(f"seat_limit_exceeded:{used}/{quota['seats_limit']}", 409)
            if db.execute(
                "select 1 from public.tenant_invitations where tenant_id=%s and email=%s and status='pending'",
                (user.tenant_id, command.email),
            ).fetchone():
                raise IntegrationError("invitation_already_pending", 409)
            row = db.execute(
                "insert into public.tenant_invitations(tenant_id,email,role,invited_by) values(%s,%s,%s,%s) returning id,version",
                (user.tenant_id, command.email, command.role, user.user_id),
            ).fetchone()
            assert row
            self.audit(db, user, "license.invite", command.reason, row["id"])
            return dict(row)

    def activate(
        self, user: AuthenticatedUser, id: UUID, command: ActivateCommand
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authorize(db, user)
            invitation = db.execute(
                "select * from public.tenant_invitations where tenant_id=%s and id=%s for update",
                (user.tenant_id, id),
            ).fetchone()
            if not invitation:
                raise IntegrationError("invitation_unavailable", 404)
            if (
                invitation["status"] != "pending"
                or invitation["version"] != command.expected_version
            ):
                raise IntegrationError("version_conflict", 409)
            account = db.execute(
                "select 1 from auth.users u where u.id=%s and lower(u.email)=%s and u.email_confirmed_at is not null and not exists(select 1 from private.provider_operators p where p.user_id=u.id)",
                (command.user_id, invitation["email"]),
            ).fetchone()
            if not account:
                raise IntegrationError("verified_account_required", 422)
            db.execute(
                "update public.tenant_invitations set status='accepted',accepted_by=%s,version=version+1 where tenant_id=%s and id=%s",
                (command.user_id, user.tenant_id, id),
            )
            # The reserved invitation seat is exchanged for an active membership atomically.
            db.execute(
                "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,%s) on conflict(tenant_id,user_id) do update set active=true,role=excluded.role,updated_at=now()",
                (user.tenant_id, command.user_id, invitation["role"]),
            )
            db.execute(
                "update auth.users set raw_app_meta_data=coalesce(raw_app_meta_data,'{}'::jsonb)||jsonb_build_object('active_tenant_id',%s::text) where id=%s and raw_app_meta_data->>'active_tenant_id' is null",
                (str(user.tenant_id), command.user_id),
            )
            self.audit(db, user, "license.activate", command.reason, command.user_id)
            return {"activated": True}

    def membership(
        self, user: AuthenticatedUser, id: UUID, command: MembershipCommand
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authorize(db, user)
            if id == user.user_id:
                raise IntegrationError("self_membership_change_denied", 409)
            row = db.execute(
                "select role,active,version from public.memberships where tenant_id=%s and user_id=%s for update",
                (user.tenant_id, id),
            ).fetchone()
            if not row:
                raise IntegrationError("membership_unavailable", 404)
            if row["version"] != command.expected_version:
                raise IntegrationError("version_conflict", 409)
            db.execute(
                "update public.memberships set active=%s,updated_at=now() where tenant_id=%s and user_id=%s",
                (command.active, user.tenant_id, id),
            )
            self.audit(db, user, "license.membership", command.reason, id)
            return {"active": command.active}

    def cancel(
        self, user: AuthenticatedUser, id: UUID, command: MembershipCommand
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authorize(db, user)
            row = db.execute(
                "update public.tenant_invitations set status='cancelled',version=version+1 where tenant_id=%s and id=%s and version=%s and status='pending' returning id",
                (user.tenant_id, id, command.expected_version),
            ).fetchone()
            if not row:
                raise IntegrationError("version_conflict", 409)
            self.audit(db, user, "license.cancel", command.reason, id)
            return {"cancelled": True}
