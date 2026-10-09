import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.provider.models import (
    CreateTenant,
    ProviderPrincipal,
    SetEntitlement,
    SetInitialAdmin,
    SetPackage,
    SetTenantStatus,
)


class ProviderDenied(Exception):
    pass


class ProviderMissing(Exception):
    pass


class ProviderConflict(Exception):
    def __init__(self, code: str, version: int | None = None):
        self.code, self.version = code, version


FIELDS = "id,name,slug,status,version,created_at,updated_at"
PACKAGE_MODULES = {
    "stellar": frozenset({"stellar"}),
    "ares_connect": frozenset({"ares_connect"}),
    "ares_crm": frozenset({"ares_crm"}),
    "full_connect": frozenset({"stellar", "ares_connect"}),
    "full_crm": frozenset({"stellar", "ares_crm"}),
}
MODULES_PACKAGE = {modules: code for code, modules in PACKAGE_MODULES.items()}


class ProviderService:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @contextmanager
    def db(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            db.execute("set local statement_timeout='5s'")
            yield db

    def authorize(self, db: psycopg.Connection[Any], actor: ProviderPrincipal) -> None:
        allowed = db.execute(
            "select 1 from private.provider_operators p "
            "join auth.sessions s on s.user_id=p.user_id and s.id=%s "
            "where p.user_id=%s and p.active and (s.not_after is null or s.not_after>now()) "
            "and not exists(select 1 from public.memberships m where m.user_id=p.user_id) "
            "for share of p,s",
            (actor.session_id, actor.user_id),
        ).fetchone()
        if not allowed:
            raise ProviderDenied

    def audit(
        self,
        db: psycopg.Connection[Any],
        actor: ProviderPrincipal,
        tenant: UUID,
        action: str,
        reason: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        def data(value: Any) -> Jsonb:
            return Jsonb(json.loads(json.dumps(value, default=str)))

        db.execute(
            "insert into public.provider_audit(actor_id,tenant_id,action,reason,before_state,"
            "after_state,correlation_id) values(%s,%s,%s,%s,%s,%s,%s)",
            (actor.user_id, tenant, action, reason, data(before), data(after), uuid4()),
        )

    def list_tenants(
        self, actor: ProviderPrincipal, cursor: UUID | None, limit: int
    ) -> dict[str, Any]:
        with self.db() as db:
            self.authorize(db, actor)
            rows = db.execute(
                f"select {FIELDS} from public.tenants where (%s::uuid is null or id>%s) "
                "order by id limit %s",
                (cursor, cursor, limit + 1),
            ).fetchall()
            page = [dict(row) for row in rows[:limit]]
            ids = [row["id"] for row in page]
            if ids:
                entitlements = db.execute(
                    "select tenant_id,module,status,expires_at from public.tenant_entitlements "
                    "where tenant_id=any(%s)",
                    (ids,),
                ).fetchall()
                billing = db.execute(
                    "select tenant_id,state,grace_until from public.tenant_billing_state "
                    "where tenant_id=any(%s)",
                    (ids,),
                ).fetchall()
                quotas = db.execute(
                    "select tenant_id,seats_limit from public.tenant_quotas "
                    "where tenant_id=any(%s)",
                    (ids,),
                ).fetchall()
                for row in page:
                    active = [
                        item
                        for item in entitlements
                        if item["tenant_id"] == row["id"] and item["status"] == "active"
                    ]
                    row["package_code"] = MODULES_PACKAGE.get(
                        frozenset(item["module"] for item in active)
                    )
                    expiries = [item["expires_at"] for item in active if item["expires_at"]]
                    row["package_expires_at"] = min(expiries) if expiries else None
                    bill = next((item for item in billing if item["tenant_id"] == row["id"]), None)
                    quota = next((item for item in quotas if item["tenant_id"] == row["id"]), None)
                    row["billing_state"] = bill["state"] if bill else None
                    row["grace_until"] = bill["grace_until"] if bill else None
                    row["seats_limit"] = quota["seats_limit"] if quota else None
            for row in page:
                self.audit(db, actor, row["id"], "tenant.list", "Provider tenant directory")
            return {
                "items": page,
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }

    def detail(self, actor: ProviderPrincipal, tenant: UUID) -> dict[str, Any]:
        with self.db() as db:
            self.authorize(db, actor)
            row = db.execute(
                f"select {FIELDS} from public.tenants where id=%s", (tenant,)
            ).fetchone()
            if not row:
                raise ProviderMissing
            entitlements = db.execute(
                "select module,status,granted_at,expires_at from public.tenant_entitlements "
                "where tenant_id=%s order by module",
                (tenant,),
            ).fetchall()
            self.audit(db, actor, tenant, "tenant.read", "Provider configuration review")
            billing = db.execute(
                "select state,due_since,grace_until,reason,changed_at "
                "from public.tenant_billing_state where tenant_id=%s",
                (tenant,),
            ).fetchone()
            quota = db.execute(
                "select * from public.tenant_quotas where tenant_id=%s", (tenant,)
            ).fetchone()
            admin = db.execute(
                "select 1 from public.memberships where tenant_id=%s "
                "and role='admin' and active limit 1",
                (tenant,),
            ).fetchone()
            usage = db.execute(
                """
                select
                  (select count(*) from public.memberships
                   where tenant_id=t.id and active)::integer active_members,
                  (select count(*) from public.tenant_invitations
                   where tenant_id=t.id and status='pending')::integer pending_invitations,
                  coalesce(sum(u.ai_spend_brl) filter (
                    where u.day=(now() at time zone t.timezone)::date), 0) ai_spend_today_brl,
                  coalesce(sum(u.ai_spend_brl) filter (
                    where u.day>=date_trunc('month', now() at time zone t.timezone)::date), 0)
                    ai_spend_month_brl,
                  coalesce(sum(u.agent_runs) filter (
                    where u.day=(now() at time zone t.timezone)::date), 0)::integer
                    agent_runs_today,
                  coalesce(sum(u.agent_runs) filter (
                    where u.day>=date_trunc('month', now() at time zone t.timezone)::date),
                    0)::integer
                    agent_runs_month
                from public.tenants t
                left join public.tenant_usage_daily u on u.tenant_id=t.id
                where t.id=%s
                group by t.id, t.timezone
                """,
                (tenant,),
            ).fetchone()
            assert usage is not None
            return {
                "tenant": row,
                "entitlements": entitlements,
                "billing": billing,
                "quota": quota,
                "usage": usage,
                "initial_admin_assigned": admin is not None,
            }

    def create(self, actor: ProviderPrincipal, command: CreateTenant) -> dict[str, Any]:
        with self.db() as db:
            return self.create_on(db, actor, command)

    def create_on(
        self, db: psycopg.Connection[Any], actor: ProviderPrincipal, command: CreateTenant
    ) -> dict[str, Any]:
        self.authorize(db, actor)
        row = db.execute(
            "insert into public.tenants(name,slug,status) "
            f"values(%s,%s,'suspended') returning {FIELDS}",
            (command.name, command.slug),
        ).fetchone()
        assert row
        self.audit(db, actor, row["id"], "tenant.create", command.reason, after=row)
        return dict(row)

    def set_status(
        self, actor: ProviderPrincipal, tenant: UUID, command: SetTenantStatus
    ) -> dict[str, Any]:
        with self.db() as db:
            return self.set_status_on(db, actor, tenant, command)

    def assign_initial_admin(
        self, actor: ProviderPrincipal, tenant: UUID, command: SetInitialAdmin
    ) -> dict[str, Any]:
        with self.db() as db:
            return self.assign_initial_admin_on(db, actor, tenant, command)

    def assign_initial_admin_on(
        self,
        db: psycopg.Connection[Any],
        actor: ProviderPrincipal,
        tenant: UUID,
        command: SetInitialAdmin,
    ) -> dict[str, Any]:
        self.authorize(db, actor)
        row = db.execute(
            f"select {FIELDS} from public.tenants where id=%s for update", (tenant,)
        ).fetchone()
        if not row:
            raise ProviderMissing
        if row["version"] != command.expected_version:
            raise ProviderConflict("version_conflict", row["version"])
        existing = db.execute(
            "select 1 from public.memberships where tenant_id=%s limit 1", (tenant,)
        ).fetchone()
        if existing:
            raise ProviderConflict("initial_admin_already_assigned", row["version"])
        quota = db.execute(
            "select seats_limit from public.tenant_quotas where tenant_id=%s", (tenant,)
        ).fetchone()
        if not quota or quota["seats_limit"] < 1:
            raise ProviderConflict("initial_admin_requires_seat", row["version"])
        account = db.execute(
            "select u.id from auth.users u where lower(u.email)=%s "
            "and u.email_confirmed_at is not null "
            "and (u.raw_app_meta_data->>'active_tenant_id' is null "
            "or u.raw_app_meta_data->>'active_tenant_id'=%s) "
            "and not exists(select 1 from private.provider_operators p where p.user_id=u.id)",
            (command.email, str(tenant)),
        ).fetchone()
        if not account:
            raise ProviderConflict("verified_initial_admin_required", row["version"])
        db.execute(
            "insert into public.memberships(tenant_id,user_id,role,active) "
            "values(%s,%s,'admin',true)",
            (tenant, account["id"]),
        )
        db.execute(
            "update auth.users set raw_app_meta_data="
            "coalesce(raw_app_meta_data,'{}'::jsonb)||"
            "jsonb_build_object('active_tenant_id',%s::text) where id=%s",
            (str(tenant), account["id"]),
        )
        updated = db.execute(
            f"update public.tenants set version=version+1,updated_at=now() "
            f"where id=%s returning {FIELDS}",
            (tenant,),
        ).fetchone()
        assert updated
        self.audit(
            db,
            actor,
            tenant,
            "tenant.initial_admin",
            command.reason,
            after={"user_id": str(account["id"]), "version": updated["version"]},
        )
        return dict(updated)

    def set_status_on(
        self,
        db: psycopg.Connection[Any],
        actor: ProviderPrincipal,
        tenant: UUID,
        command: SetTenantStatus,
    ) -> dict[str, Any]:
        self.authorize(db, actor)
        before = db.execute(
            f"select {FIELDS} from public.tenants where id=%s for update", (tenant,)
        ).fetchone()
        if not before:
            raise ProviderMissing
        if before["version"] != command.expected_version:
            raise ProviderConflict("version_conflict", before["version"])
        if command.status == "active":
            ready = db.execute(
                "select exists(select 1 from public.tenant_entitlements where tenant_id=%s "
                "and status='active' and (expires_at is null or expires_at>now())) plan_ready, "
                "exists(select 1 from public.tenant_quotas where tenant_id=%s) quota_ready, "
                "exists(select 1 from public.tenant_billing_state where tenant_id=%s "
                "and state='active') billing_ready, "
                "exists(select 1 from public.memberships where tenant_id=%s "
                "and role='admin' and active) admin_ready",
                (tenant, tenant, tenant, tenant),
            ).fetchone()
            assert ready
            if not ready["plan_ready"]:
                raise ProviderConflict("company_activation_requires_plan")
            if not ready["quota_ready"]:
                raise ProviderConflict("company_activation_requires_quota")
            if not ready["billing_ready"]:
                raise ProviderConflict("company_activation_requires_billing")
            if not ready["admin_ready"]:
                raise ProviderConflict("company_activation_requires_admin")
        after = db.execute(
            f"update public.tenants set status=%s,version=version+1,updated_at=now() "
            f"where id=%s returning {FIELDS}",
            (command.status, tenant),
        ).fetchone()
        assert after
        self.audit(db, actor, tenant, "tenant.status", command.reason, before, after)
        return dict(after)

    def assign_package(
        self, actor: ProviderPrincipal, tenant: UUID, command: SetPackage
    ) -> dict[str, Any]:
        with self.db() as db:
            return self.assign_package_on(db, actor, tenant, command)

    def assign_package_on(
        self,
        db: psycopg.Connection[Any],
        actor: ProviderPrincipal,
        tenant: UUID,
        command: SetPackage,
    ) -> dict[str, Any]:
        self.authorize(db, actor)
        row = db.execute(
            f"select {FIELDS} from public.tenants where id=%s for update", (tenant,)
        ).fetchone()
        if not row:
            raise ProviderMissing
        if row["version"] != command.expected_version:
            raise ProviderConflict("version_conflict", row["version"])
        previous = db.execute(
            "select module,status,expires_at from public.tenant_entitlements where tenant_id=%s",
            (tenant,),
        ).fetchall()
        selected = PACKAGE_MODULES[command.package]
        former_funnel = {
            item["module"] for item in previous if item["module"] in {"ares_connect", "ares_crm"}
        }
        target_funnel = selected.intersection({"ares_connect", "ares_crm"})
        if former_funnel and target_funnel and former_funnel != target_funnel:
            raise ProviderConflict("funnel_migration_required", row["version"])
        db.execute(
            "update public.tenant_entitlements set status='suspended' "
            "where tenant_id=%s and module<>all(%s) and status='active'",
            (tenant, list(selected)),
        )
        for module in selected:
            db.execute(
                "insert into public.tenant_entitlements"
                "(tenant_id,module,status,granted_by,expires_at) values(%s,%s,'active',%s,%s) "
                "on conflict(tenant_id,module) do update set status='active',"
                "granted_by=excluded.granted_by,"
                "expires_at=excluded.expires_at,granted_at=now()",
                (tenant, module, actor.user_id, command.expires_at),
            )
        updated = db.execute(
            f"update public.tenants set version=version+1,updated_at=now() "
            f"where id=%s returning {FIELDS}",
            (tenant,),
        ).fetchone()
        assert updated
        self.audit(
            db,
            actor,
            tenant,
            "package.assign",
            command.reason,
            before={"version": row["version"], "entitlements": previous},
            after={"version": updated["version"], **command.model_dump(mode="json")},
        )
        return dict(updated)

    def entitle(
        self, actor: ProviderPrincipal, tenant: UUID, command: SetEntitlement
    ) -> dict[str, Any]:
        with self.db() as db:
            return self.entitle_on(db, actor, tenant, command)

    def entitle_on(
        self,
        db: psycopg.Connection[Any],
        actor: ProviderPrincipal,
        tenant: UUID,
        command: SetEntitlement,
    ) -> dict[str, Any]:
        self.authorize(db, actor)
        row = db.execute(
            f"select {FIELDS} from public.tenants where id=%s for update", (tenant,)
        ).fetchone()
        if not row:
            raise ProviderMissing
        if row["version"] != command.expected_version:
            raise ProviderConflict("version_conflict", row["version"])
        previous = db.execute(
            "select module,status,expires_at from public.tenant_entitlements where tenant_id=%s",
            (tenant,),
        ).fetchall()
        if (
            command.module in {"ares_connect", "ares_crm"}
            and command.status == "active"
            and any(
                item["module"] in {"ares_connect", "ares_crm"} and item["module"] != command.module
                for item in previous
            )
        ):
            raise ProviderConflict("funnel_migration_required", row["version"])
        db.execute(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by,expires_at) "
            "values(%s,%s,%s,%s,%s) on conflict(tenant_id,module) do update set "
            "status=excluded.status,granted_by=excluded.granted_by,expires_at=excluded.expires_at,"
            "granted_at=now()",
            (tenant, command.module, command.status, actor.user_id, command.expires_at),
        )
        updated = db.execute(
            "update public.tenants set version=version+1,updated_at=now() "
            f"where id=%s returning {FIELDS}",
            (tenant,),
        ).fetchone()
        assert updated
        self.audit(
            db,
            actor,
            tenant,
            "entitlement.set",
            command.reason,
            before={"version": row["version"], "entitlements": previous},
            after={"version": updated["version"], **command.model_dump(mode="json")},
        )
        return dict(updated)
