import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.provider.models import CreateTenant, ProviderPrincipal, SetEntitlement


class ProviderDenied(Exception):
    pass


class ProviderMissing(Exception):
    pass


class ProviderConflict(Exception):
    def __init__(self, code: str, version: int | None = None):
        self.code, self.version = code, version


FIELDS = "id,name,slug,status,version,created_at,updated_at"


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
            for row in rows[:limit]:
                self.audit(db, actor, row["id"], "tenant.list", "Provider tenant directory")
            return {
                "items": rows[:limit],
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
            return {"tenant": row, "entitlements": entitlements, "billing": billing, "quota": quota}

    def create(self, actor: ProviderPrincipal, command: CreateTenant) -> dict[str, Any]:
        with self.db() as db:
            return self.create_on(db, actor, command)

    def create_on(
        self, db: psycopg.Connection[Any], actor: ProviderPrincipal, command: CreateTenant
    ) -> dict[str, Any]:
        self.authorize(db, actor)
        row = db.execute(
            f"insert into public.tenants(name,slug) values(%s,%s) returning {FIELDS}",
            (command.name, command.slug),
        ).fetchone()
        assert row
        self.audit(db, actor, row["id"], "tenant.create", command.reason, after=row)
        return dict(row)

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
