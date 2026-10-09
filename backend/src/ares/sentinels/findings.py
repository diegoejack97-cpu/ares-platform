"""Deterministic detector and immutable finding revisions; no CRM side effects."""

# ruff: noqa: E501
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from ares.intelligence.context_builder import fingerprint
from ares.sentinels.models import SentinelCriteria

DUE = {"sla_overdue": "o.sla_at", "unassigned": "o.opened_at", "stale": "o.updated_at"}
CONDITION = {
    "sla_overdue": "o.sla_at is not null",
    "unassigned": "o.owner_user_id is null",
    "stale": "true",
}


def predicate(schedule: dict[str, Any]) -> tuple[str, list[Any]]:
    criteria = SentinelCriteria.model_validate(schedule.get("criteria_json", {}))
    parts = [
        "o.tenant_id=%s",
        "o.state<>'closed'",
        CONDITION[schedule["kind"]],
        f"{DUE[schedule['kind']]}+make_interval(hours=>%s)<=clock_timestamp()",
    ]
    values: list[Any] = [schedule["tenant_id"], schedule["threshold_hours"]]
    if criteria.stages:
        parts.append("d.canonical_stage=any(%s)")
        values.append(criteria.stages)
    if criteria.owner_user_id:
        parts.append("o.owner_user_id=%s")
        values.append(criteria.owner_user_id)
    if criteria.currency:
        parts.append("d.currency=%s")
        values.append(criteria.currency)
    if criteria.min_value is not None:
        parts.append("d.value>=%s")
        values.append(criteria.min_value)
    if criteria.max_value is not None:
        parts.append("d.value<=%s")
        values.append(criteria.max_value)
    if criteria.risk_types:
        parts.append(
            "exists(select 1 from public.signals sig where sig.tenant_id=o.tenant_id and sig.opportunity_id=o.id and sig.signal_type=any(%s))"
        )
        values.append(criteria.risk_types)
    return " and ".join(parts), values


def snapshot_expression(kind: str) -> str:
    return f"jsonb_build_object('opportunity_id',o.id,'deal_id',o.deal_id,'sla_at',o.sla_at,'state',o.state,'priority',o.priority,'score',o.score,'owner_user_id',o.owner_user_id,'title',d.title,'stage',d.canonical_stage,'value',d.value::text,'currency',d.currency,'due_at',{DUE[kind]}+make_interval(hours=>%s))"


def event(
    db: psycopg.Connection[Any], row: dict[str, Any], schedule: dict[str, Any] | None = None
) -> dict[str, Any]:
    snapshot = {
        "finding": row["evidence"],
        "rule_id": row["rule_id"],
        "rule_version": row["rule_version"],
        "status": row["status"],
    }
    if schedule:
        snapshot["rule"] = {
            key: schedule.get(key)
            for key in ("kind", "threshold_hours", "criteria_json", "calendar_json", "title")
        }
    result = db.execute(
        "insert into public.sentinel_finding_events(tenant_id,finding_id,revision,status,snapshot_json,content_hash) values(%s,%s,%s,%s,%s,%s) returning *",
        (
            row["tenant_id"],
            row["id"],
            row["revision"],
            row["status"],
            Jsonb(snapshot),
            fingerprint(snapshot),
        ),
    ).fetchone()
    assert result
    return dict(result)


def candidates(
    db: psycopg.Connection[Any], schedule: dict[str, Any], limit: int, *, changed_only: bool = True
) -> tuple[list[dict[str, Any]], int]:
    where, params = predicate(schedule)
    expr = snapshot_expression(schedule["kind"])
    changed = (
        "and (f.id is null or f.evidence is distinct from observed or f.rule_version<>%s or f.status not in ('open','updated'))"
        if changed_only
        else ""
    )
    sql = f"""with matches as (
      select o.id opportunity_id,{DUE[schedule["kind"]]}+make_interval(hours=>%s) due_at,
        {expr} observed,o.correlation_id
      from public.ares_opportunities o left join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id
      where {where}
    ) select m.*,f.id prior_id from matches m left join public.sentinel_findings f
      on f.tenant_id=%s and f.opportunity_id=m.opportunity_id and f.rule_id=%s and f.due_at=m.due_at
      where true {changed} order by m.due_at,m.opportunity_id limit %s"""
    values = [
        schedule["threshold_hours"],
        schedule["threshold_hours"],
        *params,
        schedule["tenant_id"],
        schedule["rule_id"],
    ]
    if changed_only:
        values.append(str(schedule["version"]))
    values.append(limit)
    rows = db.execute(sql, values).fetchall()
    count = db.execute(
        f"select count(*) count from public.ares_opportunities o left join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id where {where}",
        params,
    ).fetchone()
    return rows, int(count["count"]) if count else 0


def scan_schedule(
    db: psycopg.Connection[Any], schedule: dict[str, Any], limit: int
) -> tuple[int, int, bool]:
    where, params = predicate(schedule)
    # Evaluate disappearance over the full rule population, not just the bounded batch.
    retired = db.execute(
        f"""update public.sentinel_findings f set
      status=case when rule_version<>%s then 'superseded' else 'resolved' end,
      revision=revision+1,updated_at=now(),resolved_at=now(),interpretation_status='superseded'
      where f.tenant_id=%s and f.rule_id=%s and f.status in ('open','updated') and
      (f.rule_version<>%s or not exists(select 1 from public.ares_opportunities o
      left join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id
      where o.id=f.opportunity_id and {where} and {DUE[schedule["kind"]]}+make_interval(hours=>%s)=f.due_at)) returning f.*""",
        (
            str(schedule["version"]),
            schedule["tenant_id"],
            schedule["rule_id"],
            str(schedule["version"]),
            *params,
            schedule["threshold_hours"],
        ),
    ).fetchall()
    for row in retired:
        event(db, row)
    rows, matched = candidates(db, schedule, limit)
    created = 0
    for candidate in rows:
        evidence = {
            **candidate["observed"],
            "kind": schedule["kind"],
            "threshold_hours": schedule["threshold_hours"],
            "criteria": schedule.get("criteria_json", {}),
        }
        # Criteria are versioned on the rule; observed data equality above ignores config metadata.
        priority = evidence.get("priority")
        severity = {0: "critical", 1: "high", 2: "normal", 3: "low"}.get(
            priority if isinstance(priority, int) else 3, "normal"
        )
        summary = f"{schedule['title']}: condição detectada na oportunidade."
        # Store only the comparable observed object; rule filters live in the versioned event.
        evidence = candidate["observed"]
        row = db.execute(
            """insert into public.sentinel_findings(tenant_id,opportunity_id,rule_id,rule_version,due_at,evidence,correlation_id,condition_hash,severity,summary,interpretation_status)
          values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          on conflict(tenant_id,opportunity_id,rule_id,due_at) do update set
            evidence=excluded.evidence,rule_version=excluded.rule_version,condition_hash=excluded.condition_hash,
            severity=excluded.severity,summary=excluded.summary,status='updated',revision=sentinel_findings.revision+1,
            updated_at=now(),resolved_at=null,interpretation_json=null,interpretation_run_id=null,
            interpretation_status=excluded.interpretation_status returning *""",
            (
                schedule["tenant_id"],
                candidate["opportunity_id"],
                schedule["rule_id"],
                str(schedule["version"]),
                candidate["due_at"],
                Jsonb(evidence),
                candidate["correlation_id"] or uuid4(),
                fingerprint(evidence),
                severity,
                summary,
                "pending" if schedule["interpret_with_ai"] else "not_requested",
            ),
        ).fetchone()
        assert row
        recorded = event(db, row, schedule)
        if schedule["interpret_with_ai"]:
            db.execute(
                "insert into public.jobs(tenant_id,kind,payload,correlation_id) values(%s,'sentinel.interpret',%s,%s)",
                (
                    schedule["tenant_id"],
                    Jsonb(
                        {
                            "finding_id": str(row["id"]),
                            "revision": row["revision"],
                            "context_ref": str(recorded["id"]),
                        }
                    ),
                    row["correlation_id"],
                ),
            )
        created += int(candidate["prior_id"] is None)
    return created, matched, len(rows) >= limit
