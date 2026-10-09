"""Personal notification state over shared findings, with fresh portfolio authorization."""

# ruff: noqa: E501
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.sentinels.service import SentinelScheduleConflict


def scope_on(
    db: psycopg.Connection[Any], user: AuthenticatedUser, *, admin: bool = False
) -> UUID | None:
    membership = db.execute(
        "select m.role::text role from public.memberships m join public.tenants t on t.id=m.tenant_id where m.tenant_id=%s and m.user_id=%s and m.active and t.status='active' and exists(select 1 from public.tenant_entitlements e where e.tenant_id=t.id and e.module='ares_connect' and e.status='active' and (e.expires_at is null or e.expires_at>clock_timestamp())) for share of m,t",
        (user.tenant_id, user.user_id),
    ).fetchone()
    if not membership or (admin and membership["role"] != "admin"):
        raise SentinelScheduleConflict("sentinel_access_denied")
    return user.user_id if membership["role"] == "seller" else None


class NotificationService:
    def __init__(self, url: str):
        self.url = url

    def list_sync(
        self, user: AuthenticatedUser, limit: int = 10, offset: int = 0, view: str = "all"
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute("set local statement_timeout='5s'")
            owner = scope_on(db, user)
            base = """from public.sentinel_findings f
              join public.ares_opportunities o on o.tenant_id=f.tenant_id and o.id=f.opportunity_id
              join public.sentinel_schedules s on s.tenant_id=f.tenant_id and s.rule_id=f.rule_id
              left join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id
              left join public.sentinel_notification_state n on n.tenant_id=f.tenant_id and n.finding_id=f.id and n.user_id=%s
              where f.tenant_id=%s and (%s::uuid is null or o.owner_user_id=%s)"""
            params = [user.user_id, user.tenant_id, owner, owner]
            # Counts and page use exactly the same scope and one consistent snapshot statement.
            row = db.execute(
                f"""with scoped as (select f.*,d.title,s.title rule_title,
                coalesce(n.read_revision,0)>=f.revision is_read,
                coalesce(n.archived_revision,0)>=f.revision is_archived {base}),
              selected as (select f.id,f.opportunity_id,f.rule_id,f.rule_version,f.due_at,f.detected_at,f.updated_at,f.revision,f.status,f.severity,f.summary,f.interpretation_status,f.interpretation_json,f.title,f.rule_title,f.is_read,f.is_archived
                from scoped f where {{condition}}), page as (select * from selected order by updated_at desc,id desc limit %s offset %s)
              select (select count(*) from scoped where not is_read and not is_archived) unread_count,
                (select count(*) from selected) total,
                coalesce((select jsonb_agg(to_jsonb(page) order by updated_at desc,id desc) from page),'[]'::jsonb) items""".replace(
                    "{condition}",
                    {
                        "all": "not f.is_archived",
                        "unread": "not f.is_read and not f.is_archived",
                        "archived": "f.is_archived",
                    }[view],
                ),
                [*params, limit, offset],
            ).fetchone()
            assert row
            return {
                **dict(row),
                "offset": offset,
                "next_offset": offset + limit if offset + limit < row["total"] else None,
                "source": "ARES Core / achados persistidos",
            }

    def mark_sync(
        self, user: AuthenticatedUser, finding: UUID, revision: int, action: str
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            owner = scope_on(db, user)
            row = db.execute(
                "select f.revision from public.sentinel_findings f join public.ares_opportunities o on o.tenant_id=f.tenant_id and o.id=f.opportunity_id where f.tenant_id=%s and f.id=%s and (%s::uuid is null or o.owner_user_id=%s) for share of f,o",
                (user.tenant_id, finding, owner, owner),
            ).fetchone()
            if not row:
                raise SentinelScheduleConflict("sentinel_finding_not_found")
            if row["revision"] != revision:
                raise SentinelScheduleConflict("stale_sentinel_finding")
            prior = db.execute(
                "select * from public.sentinel_notification_state where tenant_id=%s and finding_id=%s and user_id=%s for update",
                (user.tenant_id, finding, user.user_id),
            ).fetchone()
            read = prior["read_revision"] if prior else 0
            archived = prior["archived_revision"] if prior else 0
            if action in {"read", "archive"}:
                read = revision
            if action == "unread":
                read = 0
                archived = 0
            if action == "archive":
                archived = revision
            if action == "restore":
                archived = 0
            db.execute(
                "insert into public.sentinel_notification_state(tenant_id,finding_id,user_id,read_revision,archived_revision) values(%s,%s,%s,%s,%s) on conflict(tenant_id,finding_id,user_id) do update set read_revision=excluded.read_revision,archived_revision=excluded.archived_revision,updated_at=now()",
                (user.tenant_id, finding, user.user_id, read, archived),
            )
            return {
                "id": str(finding),
                "revision": revision,
                "is_read": read >= revision,
                "is_archived": archived >= revision,
            }
