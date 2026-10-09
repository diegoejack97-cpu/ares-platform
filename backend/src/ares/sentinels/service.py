"""Durable, tenant-scoped sentinels with typed, administrator-owned rules."""
# SQL statements remain complete for review.
# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.sentinels.findings import scan_schedule
from ares.sentinels.models import SentinelRuleCommand, SentinelScheduleCommand
from ares.sentinels.scheduling import next_calendar_at

RULE_ID = "SENTINEL-SLA-OVERDUE"
RULE_VERSION = "1"
RULE_DEFINITION = "Oportunidade ARES aberta com prazo de SLA vencido."
RULE_DEFINITIONS = {
    "sla_overdue": "Oportunidade ARES aberta com prazo de SLA vencido.",
    "unassigned": "Oportunidade ARES aberta sem responsável definido.",
    "stale": "Oportunidade ARES aberta sem atualização no intervalo definido.",
}
_DUE_EXPRESSIONS = {
    "sla_overdue": "o.sla_at + make_interval(hours => %s)",
    "unassigned": "o.opened_at + make_interval(hours => %s)",
    "stale": "o.updated_at + make_interval(hours => %s)",
}
_RULE_PREDICATES = {
    "sla_overdue": "o.sla_at is not null",
    "unassigned": "o.owner_user_id is null",
    "stale": "true",
}
SCAN_LIMIT = 50
TENANTS_PER_TICK = 5


class SentinelScheduleConflict(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def next_scheduled_at(
    now: datetime, timezone: str, start_time: time, interval_minutes: int
) -> datetime:
    """Next wall-clock slot after now, anchored to the tenant's local day."""
    zone = ZoneInfo(timezone)
    now_utc = now.astimezone(UTC)
    local_now = now_utc.astimezone(zone)
    anchor = datetime.combine(local_now.date(), start_time, tzinfo=zone)
    if local_now < anchor:
        anchor = datetime.combine(local_now.date() - timedelta(days=1), start_time, tzinfo=zone)
    minutes_since_anchor = int(
        (local_now.replace(tzinfo=None) - anchor.replace(tzinfo=None)).total_seconds() // 60
    )
    step = minutes_since_anchor // interval_minutes + 1
    candidate = (anchor + timedelta(minutes=step * interval_minutes)).astimezone(UTC)
    while candidate <= now_utc:
        step += 1
        candidate = (anchor + timedelta(minutes=step * interval_minutes)).astimezone(UTC)
    return candidate


class SentinelService:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @staticmethod
    def _schedule_payload(row: dict[str, Any]) -> dict[str, Any]:
        slots = int(row["sentinel_slots"])
        can_run = bool(
            row["enabled"]
            and slots > 0
            and row.get("archived_at") is None
            and (row.get("capacity_rank") is None or row["capacity_rank"] <= slots)
        )
        return {
            "rule_id": row["rule_id"],
            "kind": row["kind"],
            "title": row["title"],
            "definition": RULE_DEFINITIONS[row["kind"]],
            "threshold_hours": row["threshold_hours"],
            "enabled": row["enabled"],
            "interval_minutes": row["interval_minutes"],
            "start_time_local": row["start_time_local"],
            "timezone": row.get("calendar_json", {}).get("timezone") or row["timezone"],
            "criteria": row.get("criteria_json", {}),
            "calendar": row.get("calendar_json", {}),
            "interpret_with_ai": row.get("interpret_with_ai", False),
            "last_error_code": row.get("last_error_code"),
            "last_matched_count": row.get("last_matched_count"),
            "next_run_at": row["next_run_at"] if can_run else None,
            "last_run_at": row["last_run_at"],
            "last_created_count": row["last_created_count"],
            "version": row["version"],
            "updated_at": row["updated_at"],
            "sentinel_slots": slots,
            "can_run": can_run,
        }

    def schedule_sync(self, tenant_id: UUID) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                select s.*, t.timezone, coalesce(q.sentinel_slots, 0) sentinel_slots,
                       r.capacity_rank
                from public.sentinel_schedules s
                left join (
                  select tenant_id,rule_id,
                    row_number() over(partition by tenant_id order by created_at,rule_id)
                      capacity_rank
                  from public.sentinel_schedules
                  where enabled and archived_at is null
                ) r on r.tenant_id=s.tenant_id and r.rule_id=s.rule_id
                join public.tenants t on t.id=s.tenant_id
                left join public.tenant_quotas q on q.tenant_id=s.tenant_id
                where s.tenant_id=%s and s.rule_id=%s
                """,
                (tenant_id, RULE_ID),
            ).fetchone()
        if row is None:
            raise SentinelScheduleConflict("sentinel_schedule_not_found")
        return self._schedule_payload(row)

    def update_schedule_sync(
        self, tenant_id: UUID, actor_id: UUID, command: SentinelScheduleCommand
    ) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            # Keep the legacy SLA endpoint serialized with catalog rule writes.
            connection.execute(
                "select id from public.tenants where id=%s for update", (tenant_id,)
            ).fetchone()
            row = connection.execute(
                """
                select s.*, t.timezone, coalesce(q.sentinel_slots, 0) sentinel_slots
                from public.sentinel_schedules s
                join public.tenants t on t.id=s.tenant_id and t.status='active'
                left join public.tenant_quotas q on q.tenant_id=s.tenant_id
                where s.tenant_id=%s and s.rule_id=%s
                for update of s
                """,
                (tenant_id, RULE_ID),
            ).fetchone()
            if row is None:
                raise SentinelScheduleConflict("sentinel_schedule_not_found")
            if row["version"] != command.expected_version:
                raise SentinelScheduleConflict("stale_sentinel_schedule")
            if command.enabled:
                others_row = connection.execute(
                    """
                    select count(*)::integer count from public.sentinel_schedules
                    where tenant_id=%s and rule_id<>%s and enabled
                      and archived_at is null
                    """,
                    (tenant_id, RULE_ID),
                ).fetchone()
                assert others_row is not None
                others = others_row["count"]
                if others >= int(row["sentinel_slots"]):
                    raise SentinelScheduleConflict("sentinel_capacity_unavailable")
            if (
                row["enabled"] == command.enabled
                and row["interval_minutes"] == command.interval_minutes
                and row["start_time_local"] == command.start_time_local
            ):
                return self._schedule_payload(row)

            calendar = row.get("calendar_json", {})
            try:
                expanded = SentinelRuleCommand(
                    title=row["title"],
                    kind=row["kind"],
                    threshold_hours=row["threshold_hours"],
                    enabled=command.enabled,
                    interval_minutes=command.interval_minutes,
                    start_time_local=command.start_time_local,
                    reason=command.reason,
                    calendar=calendar,
                )
            except ValueError as error:
                raise SentinelScheduleConflict("sentinel_calendar_conflict") from error
            next_run = next_calendar_at(
                datetime.now(UTC),
                row["timezone"],
                command.start_time_local,
                command.interval_minutes,
                expanded.calendar,
            )
            updated = connection.execute(
                """
                update public.sentinel_schedules set enabled=%s,
                  interval_minutes=%s, start_time_local=%s, next_run_at=%s,
                  version=version+1, updated_at=now(), updated_by=%s
                where tenant_id=%s and rule_id=%s returning *
                """,
                (
                    command.enabled,
                    command.interval_minutes,
                    command.start_time_local,
                    next_run,
                    actor_id,
                    tenant_id,
                    RULE_ID,
                ),
            ).fetchone()
            assert updated is not None
            connection.execute(
                """
                insert into public.sentinel_schedule_audit
                  (tenant_id,rule_id,actor_user_id,reason,prior_config,next_config)
                values (%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    RULE_ID,
                    actor_id,
                    command.reason,
                    Jsonb(
                        {
                            "enabled": row["enabled"],
                            "interval_minutes": row["interval_minutes"],
                            "start_time_local": row["start_time_local"].isoformat(),
                            "version": row["version"],
                        }
                    ),
                    Jsonb(
                        {
                            "enabled": updated["enabled"],
                            "interval_minutes": updated["interval_minutes"],
                            "start_time_local": updated["start_time_local"].isoformat(),
                            "version": updated["version"],
                        }
                    ),
                ),
            )
            updated["timezone"] = row["timezone"]
            updated["sentinel_slots"] = row["sentinel_slots"]
            return self._schedule_payload(updated)

    def catalog_sync(self, tenant_id: UUID) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                select s.*, t.timezone, coalesce(q.sentinel_slots, 0) sentinel_slots,
                       r.capacity_rank
                from public.sentinel_schedules s
                left join (
                  select tenant_id,rule_id,
                    row_number() over(partition by tenant_id order by created_at,rule_id)
                      capacity_rank
                  from public.sentinel_schedules
                  where enabled and archived_at is null
                ) r on r.tenant_id=s.tenant_id and r.rule_id=s.rule_id
                join public.tenants t on t.id=s.tenant_id
                left join public.tenant_quotas q on q.tenant_id=s.tenant_id
                where s.tenant_id=%s and s.archived_at is null
                order by s.created_at, s.rule_id
                """,
                (tenant_id,),
            ).fetchall()
            tenant = connection.execute(
                """
                select t.timezone, coalesce(q.sentinel_slots, 0) sentinel_slots
                from public.tenants t left join public.tenant_quotas q on q.tenant_id=t.id
                where t.id=%s
                """,
                (tenant_id,),
            ).fetchone()
        if tenant is None:
            raise SentinelScheduleConflict("sentinel_schedule_not_found")
        return {
            "items": [self._schedule_payload(row) for row in rows],
            "sentinel_slots": tenant["sentinel_slots"],
            "active_count": min(
                sum(bool(row["enabled"]) for row in rows), tenant["sentinel_slots"]
            ),
            "timezone": tenant["timezone"],
        }

    @staticmethod
    def _audit_config(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        return {
            "title": row["title"],
            "kind": row["kind"],
            "threshold_hours": row["threshold_hours"],
            "enabled": row["enabled"],
            "interval_minutes": row["interval_minutes"],
            "start_time_local": row["start_time_local"].isoformat(),
            "archived_at": row["archived_at"].isoformat() if row["archived_at"] else None,
            "version": row["version"],
            "criteria": row.get("criteria_json", {}),
            "calendar": row.get("calendar_json", {}),
            "interpret_with_ai": row.get("interpret_with_ai", False),
        }

    def save_rule_sync(
        self,
        tenant_id: UUID,
        actor_id: UUID,
        command: SentinelRuleCommand,
        rule_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a typed rule under the tenant's contracted capacity."""
        if (rule_id is None) != (command.expected_version is None):
            raise SentinelScheduleConflict("sentinel_version_required")
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            quota = connection.execute(
                """
                select t.timezone, coalesce(q.sentinel_slots, 0) sentinel_slots
                from public.tenants t
                left join public.tenant_quotas q on q.tenant_id=t.id
                where t.id=%s and t.status='active'
                for update of t
                """,
                (tenant_id,),
            ).fetchone()
            if quota is None:
                raise SentinelScheduleConflict("sentinel_schedule_not_found")
            previous = None
            if rule_id is not None:
                previous = connection.execute(
                    """
                    select * from public.sentinel_schedules
                    where tenant_id=%s and rule_id=%s and archived_at is null
                    for update
                    """,
                    (tenant_id, rule_id),
                ).fetchone()
                if previous is None:
                    raise SentinelScheduleConflict("sentinel_schedule_not_found")
                if previous["version"] != command.expected_version:
                    raise SentinelScheduleConflict("stale_sentinel_schedule")
                if previous["kind"] != command.kind:
                    raise SentinelScheduleConflict("sentinel_kind_immutable")
            active_count_row = connection.execute(
                """
                select count(*)::integer count from public.sentinel_schedules
                where tenant_id=%s and enabled and archived_at is null
                  and (%s::text is null or rule_id<>%s::text)
                """,
                (tenant_id, rule_id, rule_id),
            ).fetchone()
            assert active_count_row is not None
            active_count = active_count_row["count"]
            if command.enabled and active_count >= quota["sentinel_slots"]:
                raise SentinelScheduleConflict("sentinel_capacity_unavailable")
            now = datetime.now(UTC)
            next_run = next_calendar_at(
                now,
                quota["timezone"],
                command.start_time_local,
                command.interval_minutes,
                command.calendar,
            )
            if (
                command.criteria.owner_user_id
                and not connection.execute(
                    "select 1 from public.memberships where tenant_id=%s and user_id=%s and active",
                    (tenant_id, command.criteria.owner_user_id),
                ).fetchone()
            ):
                raise SentinelScheduleConflict("sentinel_owner_unavailable")
            if (
                command.interpret_with_ai
                and not connection.execute(
                    "select 1 from public.tenant_quotas where tenant_id=%s and agent_slots>=1",
                    (tenant_id,),
                ).fetchone()
            ):
                raise SentinelScheduleConflict("sentinel_agent_capacity_unavailable")
            if previous is None:
                rule_id = f"SENTINEL-{uuid4()}"
                updated = connection.execute(
                    """
                    insert into public.sentinel_schedules
                      (tenant_id,rule_id,kind,title,threshold_hours,enabled,
                       interval_minutes,start_time_local,next_run_at,updated_by)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *
                    """,
                    (
                        tenant_id,
                        rule_id,
                        command.kind,
                        command.title,
                        command.threshold_hours,
                        command.enabled,
                        command.interval_minutes,
                        command.start_time_local,
                        next_run,
                        actor_id,
                    ),
                ).fetchone()
            else:
                updated = connection.execute(
                    """
                    update public.sentinel_schedules
                    set title=%s,threshold_hours=%s,enabled=%s,interval_minutes=%s,
                        start_time_local=%s,next_run_at=%s,updated_by=%s,
                        updated_at=now(),version=version+1
                    where tenant_id=%s and rule_id=%s returning *
                    """,
                    (
                        command.title,
                        command.threshold_hours,
                        command.enabled,
                        command.interval_minutes,
                        command.start_time_local,
                        next_run,
                        actor_id,
                        tenant_id,
                        rule_id,
                    ),
                ).fetchone()
            assert updated is not None
            updated = connection.execute(
                "update public.sentinel_schedules set criteria_json=%s,calendar_json=%s,interpret_with_ai=%s,last_error_code=null where tenant_id=%s and rule_id=%s returning *",
                (
                    Jsonb(command.criteria.model_dump(mode="json")),
                    Jsonb(command.calendar.model_dump(mode="json")),
                    command.interpret_with_ai,
                    tenant_id,
                    rule_id,
                ),
            ).fetchone()
            assert updated is not None
            connection.execute(
                """
                insert into public.sentinel_schedule_audit
                  (tenant_id,rule_id,actor_user_id,reason,prior_config,next_config)
                values (%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    rule_id,
                    actor_id,
                    command.reason,
                    Jsonb(self._audit_config(previous)),
                    Jsonb(self._audit_config(updated)),
                ),
            )
            updated["timezone"] = quota["timezone"]
            updated["sentinel_slots"] = quota["sentinel_slots"]
            return self._schedule_payload(updated)

    def archive_rule_sync(
        self, tenant_id: UUID, actor_id: UUID, rule_id: str, version: int, reason: str
    ) -> None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            previous = connection.execute(
                """
                select * from public.sentinel_schedules
                where tenant_id=%s and rule_id=%s and archived_at is null for update
                """,
                (tenant_id, rule_id),
            ).fetchone()
            if previous is None:
                raise SentinelScheduleConflict("sentinel_schedule_not_found")
            if previous["version"] != version:
                raise SentinelScheduleConflict("stale_sentinel_schedule")
            updated = connection.execute(
                """
                update public.sentinel_schedules
                set enabled=false,archived_at=now(),updated_at=now(),updated_by=%s,
                    version=version+1
                where tenant_id=%s and rule_id=%s returning *
                """,
                (actor_id, tenant_id, rule_id),
            ).fetchone()
            from ares.sentinels.findings import event

            retired = connection.execute(
                "update public.sentinel_findings set status='superseded',revision=revision+1,updated_at=now(),resolved_at=now(),interpretation_status='superseded' where tenant_id=%s and rule_id=%s and status in ('open','updated') returning *",
                (tenant_id, rule_id),
            ).fetchall()
            for finding in retired:
                event(connection, finding, previous)
            connection.execute(
                """
                insert into public.sentinel_schedule_audit
                  (tenant_id,rule_id,actor_user_id,reason,prior_config,next_config)
                values (%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    rule_id,
                    actor_id,
                    reason,
                    Jsonb(self._audit_config(previous)),
                    Jsonb(self._audit_config(updated)),
                ),
            )

    def scan_sync(self) -> int:
        """Claim due tenant schedules and persist bounded, deduplicated findings."""
        total = 0
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute("set local statement_timeout='5s'")
            schedules = connection.execute(
                """
                select s.*, t.timezone
                from public.sentinel_schedules s
                join (
                  select tenant_id,rule_id,
                    row_number() over(partition by tenant_id order by created_at,rule_id)
                      capacity_rank
                  from public.sentinel_schedules
                  where enabled and archived_at is null
                ) r on r.tenant_id=s.tenant_id and r.rule_id=s.rule_id
                join public.tenants t on t.id=s.tenant_id and t.status='active'
                join public.tenant_quotas q on q.tenant_id=s.tenant_id
                  and q.sentinel_slots >= r.capacity_rank
                where s.enabled and s.archived_at is null and s.next_run_at<=now()
                  and exists (
                    select 1 from public.tenant_entitlements e
                    where e.tenant_id=s.tenant_id and e.module='ares_connect'
                      and e.status='active'
                      and (e.expires_at is null or e.expires_at>now())
                  )
                order by s.next_run_at, s.tenant_id
                limit %s for update of s skip locked
                """,
                (TENANTS_PER_TICK,),
            ).fetchall()
            per_tenant_limit = max(1, SCAN_LIMIT // max(1, len(schedules)))
            for schedule in schedules:
                from ares.sentinels.models import SentinelCalendar
                from ares.sentinels.scheduling import calendar_allows

                calendar = SentinelCalendar.model_validate(schedule["calendar_json"])
                now = datetime.now(UTC)
                next_run = next_calendar_at(
                    now,
                    schedule["timezone"],
                    schedule["start_time_local"],
                    schedule["interval_minutes"],
                    calendar,
                )
                if not calendar_allows(
                    now, schedule["timezone"], schedule["start_time_local"], calendar
                ):
                    connection.execute(
                        "update public.sentinel_schedules set next_run_at=%s where tenant_id=%s and rule_id=%s",
                        (next_run, schedule["tenant_id"], schedule["rule_id"]),
                    )
                    continue
                try:
                    with connection.transaction():
                        created, matched, exhausted = scan_schedule(
                            connection, schedule, per_tenant_limit
                        )
                except (psycopg.Error, ValueError):
                    connection.execute(
                        "update public.sentinel_schedules set last_error_code='sentinel_scan_failed',last_run_at=now(),next_run_at=now()+interval '1 minute' where tenant_id=%s and rule_id=%s",
                        (schedule["tenant_id"], schedule["rule_id"]),
                    )
                    continue
                total += created
                if exhausted:
                    next_run = now + timedelta(seconds=10)
                connection.execute(
                    """
                    update public.sentinel_schedules
                    set next_run_at=%s,last_run_at=now(),last_created_count=%s,last_matched_count=%s,last_error_code=null
                    where tenant_id=%s and rule_id=%s
                    """,
                    (next_run, created, matched, schedule["tenant_id"], schedule["rule_id"]),
                )
                connection.execute(
                    """
                    insert into public.sentinel_scan_runs
                      (tenant_id,rule_id,created_count) values (%s,%s,%s)
                    """,
                    (schedule["tenant_id"], schedule["rule_id"], created),
                )
        return total

    def preview_sync(self, user: AuthenticatedUser, command: SentinelRuleCommand) -> dict[str, Any]:
        """Audit a bounded dry run; capacity applies, no findings, model or CRM writes."""
        from ares.decision.execution_guard import check_execution_contract
        from ares.sentinels.findings import candidates
        from ares.sentinels.notifications import scope_on

        with psycopg.connect(self._database_url, row_factory=dict_row) as db:
            db.execute("set local statement_timeout='5s'")
            scope_on(db, user, admin=True)
            check_execution_contract(db, user.tenant_id)
            quota = db.execute(
                "select sentinel_slots from public.tenant_quotas where tenant_id=%s",
                (user.tenant_id,),
            ).fetchone()
            if not quota or quota["sentinel_slots"] < 1:
                raise SentinelScheduleConflict("sentinel_capacity_unavailable")
            schedule = {
                **command.model_dump(),
                "tenant_id": user.tenant_id,
                "rule_id": "preview",
                "version": 1,
                "criteria_json": command.criteria.model_dump(mode="json"),
            }
            rows, count = candidates(db, schedule, 10, changed_only=False)
            db.execute(
                "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'user',%s,'sentinel.preview',%s,'ares',%s)",
                (
                    user.tenant_id,
                    user.user_id,
                    uuid4(),
                    Jsonb({"matched_count": count, "kind": command.kind}),
                ),
            )
            return {
                "matched_count": count,
                "items": [
                    {
                        "opportunity_id": row["opportunity_id"],
                        "title": row["observed"].get("title"),
                        "due_at": row["due_at"],
                    }
                    for row in rows
                ],
                "truncated": count > len(rows),
                "source": "ARES Core / teste sem efeitos",
                "ai_called": False,
            }

    def list_sync(
        self, tenant_id: UUID, *, limit: int = 25, reader: AuthenticatedUser | None = None
    ) -> dict[str, Any]:
        """Return current findings and the evidence captured when each fired."""
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute("set local statement_timeout='5s'")
            owner = None
            if reader is not None:
                membership = connection.execute(
                    "select m.role::text role from public.memberships m "
                    "join public.tenants t on t.id=m.tenant_id "
                    "where m.tenant_id=%s and m.user_id=%s and m.active and t.status='active' "
                    "and exists(select 1 from public.tenant_entitlements e "
                    "where e.tenant_id=t.id and e.module='ares_connect' and e.status='active' "
                    "and (e.expires_at is null or e.expires_at>now()))",
                    (tenant_id, reader.user_id),
                ).fetchone()
                if membership is None or reader.tenant_id != tenant_id:
                    return {
                        "items": [],
                        "truncated": False,
                        "source": "ARES Core",
                        "freshness_at": datetime.now(UTC),
                        "checked_at": None,
                    }
                if membership["role"] == "seller":
                    owner = reader.user_id
            rows = connection.execute(
                """
                select f.id, f.opportunity_id, f.rule_id, f.rule_version,
                       f.due_at, f.detected_at, f.evidence, f.correlation_id,
                       d.title, o.state, o.priority, s.title rule_title, s.kind rule_kind
                from public.sentinel_findings f
                join public.sentinel_schedules s
                  on s.tenant_id=f.tenant_id and s.rule_id=f.rule_id
                join (
                  select tenant_id,rule_id,
                    row_number() over(partition by tenant_id order by created_at,rule_id)
                      capacity_rank
                  from public.sentinel_schedules
                  where enabled and archived_at is null
                ) r on r.tenant_id=s.tenant_id and r.rule_id=s.rule_id
                join public.tenant_quotas q on q.tenant_id=s.tenant_id
                  and q.sentinel_slots>=r.capacity_rank
                join public.ares_opportunities o
                  on o.tenant_id=f.tenant_id and o.id=f.opportunity_id
                left join public.deals d
                  on d.tenant_id=o.tenant_id and d.id=o.deal_id
                where f.tenant_id=%s and o.state<>'closed'
                  and (%s::uuid is null or o.owner_user_id=%s)
                  and s.enabled and s.archived_at is null
                  and case s.kind
                    when 'sla_overdue' then
                      o.sla_at is not null and
                      o.sla_at+make_interval(hours=>s.threshold_hours)=f.due_at
                    when 'unassigned' then
                      o.owner_user_id is null and
                      o.opened_at+make_interval(hours=>s.threshold_hours)=f.due_at
                    when 'stale' then
                      o.updated_at+make_interval(hours=>s.threshold_hours)=f.due_at
                    else false end
                  and f.due_at<=now()
                order by f.detected_at desc, f.id limit %s
                """,
                (tenant_id, owner, owner, limit + 1),
            ).fetchall()
            scan = connection.execute(
                """
                select checked_at from public.sentinel_scan_runs
                where tenant_id=%s
                order by checked_at desc,id desc limit 1
                """,
                (tenant_id,),
            ).fetchone()
        return {
            "items": [dict(row) for row in rows[:limit]],
            "truncated": len(rows) > limit,
            "rule": {"id": RULE_ID, "version": RULE_VERSION, "definition": RULE_DEFINITION},
            "source": "ARES Core / oportunidades e evidências persistidas",
            "freshness_at": datetime.now(UTC),
            "checked_at": scan["checked_at"] if scan else None,
        }
