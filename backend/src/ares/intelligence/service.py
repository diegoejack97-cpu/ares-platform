from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.intelligence.models import CanonicalEvent, PipelineResult
from ares.intelligence.rules import evaluate
from ares.intelligence.scoring import calculate_score

CONTEXT_TOKEN_LIMIT = 2_500
STATE_TRANSITIONS: dict[str, set[str]] = {
    "detected": {"qualifying", "prioritized", "closed"},
    "qualifying": {"qualified", "prioritized", "closed"},
    "qualified": {"prioritized", "closed"},
    "prioritized": {"awaiting_decision", "closed"},
    "awaiting_decision": {"authorized", "closed"},
    "authorized": {"executing", "closed"},
    "executing": {"observing", "closed"},
    "observing": {"closed"},
    "closed": set(),
}


def validate_transition(from_state: str, to_state: str) -> None:
    if to_state not in STATE_TRANSITIONS.get(from_state, set()):
        raise ValueError(f"invalid_opportunity_transition:{from_state}->{to_state}")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _cursor_encode(row: dict[str, Any]) -> str:
    value = [
        int(row["priority"]),
        row["sla_at"].isoformat() if row["sla_at"] else "9999-12-31T23:59:59+00:00",
        -float(row["score"]),
        str(row["id"]),
    ]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _cursor_decode(value: str) -> list[Any]:
    padding = "=" * (-len(value) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(value + padding))
    if not isinstance(decoded, list) or len(decoded) != 4:
        raise ValueError("invalid_cursor")
    return decoded


class IntelligenceService:
    """M2 deterministic pipeline. It is the sole reader that creates context snapshots."""

    def __init__(self, database_url: str, tenant_id: UUID) -> None:
        self._database_url = database_url
        self._tenant_id = tenant_id

    async def process_event(self, event_id: UUID) -> PipelineResult:
        return await asyncio.to_thread(self.process_event_sync, event_id)

    def process_event_sync(self, event_id: UUID) -> PipelineResult:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            event_row = connection.execute(
                """
                select id, tenant_id, event_type, aggregate_type, aggregate_id,
                       correlation_id, occurred_at, recorded_at, data
                from public.commercial_events
                where id = %s and tenant_id = %s
                """,
                (event_id, self._tenant_id),
            ).fetchone()
            if event_row is None:
                raise ValueError("commercial_event_not_found")
            event = CanonicalEvent.model_validate(event_row)
            drafts = evaluate(event)
            if not drafts:
                return PipelineResult(event_id=event.id, signal_ids=[])

            deal = self._upsert_deal(connection, event)
            signal_ids: list[UUID] = []
            for draft in drafts:
                row = connection.execute(
                    """
                    insert into public.signals (
                      tenant_id, event_id, signal_type, rule_id, rule_version,
                      severity, evidence, correlation_id, source, source_ref
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, 'ares', %s)
                    on conflict (tenant_id, event_id, rule_id, rule_version)
                    do update set evidence = excluded.evidence
                    returning id
                    """,
                    (
                        self._tenant_id,
                        event.id,
                        draft.signal_type,
                        draft.rule_id,
                        draft.rule_version,
                        draft.severity,
                        Jsonb(_jsonable(draft.evidence)),
                        event.correlation_id,
                        str(event.id),
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError("signal_upsert_failed")
                signal_ids.append(row["id"])

            opportunity, created = self._get_or_create_opportunity(connection, deal, event)
            connection.execute(
                """
                update public.signals set opportunity_id = %s
                where tenant_id = %s and id = any(%s)
                """,
                (opportunity["id"], self._tenant_id, signal_ids),
            )
            if created:
                self._record_initial_transitions(connection, opportunity["id"], event)

            signal_rows = connection.execute(
                """
                select id, signal_type, rule_id, rule_version, severity, evidence, detected_at
                from public.signals
                where tenant_id = %s and opportunity_id = %s
                order by detected_at, id
                """,
                (self._tenant_id, opportunity["id"]),
            ).fetchall()
            score = calculate_score([dict(row) for row in signal_rows], float(deal["value"] or 0))
            score_input = {
                "signals": [
                    {
                        "id": row["id"],
                        "rule_version": row["rule_version"],
                        "severity": row["severity"],
                    }
                    for row in signal_rows
                ],
                "deal_value": deal["value"],
            }
            input_hash = _canonical_hash(score_input)
            connection.execute(
                """
                insert into public.opportunity_score_snapshots (
                  tenant_id, opportunity_id, score_version, total_score, breakdown,
                  input_hash, correlation_id, source
                ) values (%s, %s, %s, %s, %s, %s, %s, 'ares')
                on conflict (tenant_id, opportunity_id, score_version, input_hash) do nothing
                """,
                (
                    self._tenant_id,
                    opportunity["id"],
                    score.score_version,
                    score.total_score,
                    Jsonb(score.breakdown),
                    input_hash,
                    event.correlation_id,
                ),
            )
            sla_hours = (4, 12, 24, 48)[score.priority]
            primary_signal_type = max(signal_rows, key=lambda row: int(row["severity"]))[
                "signal_type"
            ]
            connection.execute(
                """
                with desired as (
                  select %s::numeric as score, %s::smallint as priority,
                    %s::text as score_version, %s::jsonb as score_breakdown,
                    %s::integer as signal_count, %s::text as primary_signal_type,
                    %s::timestamptz as sla_at, %s::timestamptz as last_activity_at,
                    %s::uuid as correlation_id
                )
                update public.ares_opportunities opportunity
                set score = desired.score, priority = desired.priority,
                    score_version = desired.score_version,
                    score_breakdown = desired.score_breakdown,
                    signal_count = desired.signal_count,
                    primary_signal_type = desired.primary_signal_type,
                    sla_at = least(coalesce(opportunity.sla_at, desired.sla_at), desired.sla_at),
                    last_activity_at = desired.last_activity_at,
                    correlation_id = desired.correlation_id,
                    updated_at = now(), version = version + 1
                from desired
                where opportunity.id = %s and opportunity.tenant_id = %s
                  and row(
                    opportunity.score, opportunity.priority, opportunity.score_version,
                    opportunity.score_breakdown, opportunity.signal_count,
                    opportunity.primary_signal_type, opportunity.sla_at,
                    opportunity.last_activity_at, opportunity.correlation_id
                  ) is distinct from row(
                    desired.score, desired.priority, desired.score_version,
                    desired.score_breakdown, desired.signal_count,
                    desired.primary_signal_type,
                    least(coalesce(opportunity.sla_at, desired.sla_at), desired.sla_at),
                    desired.last_activity_at, desired.correlation_id
                  )
                """,
                (
                    score.total_score,
                    score.priority,
                    score.score_version,
                    Jsonb(score.breakdown),
                    len(signal_rows),
                    primary_signal_type,
                    event.occurred_at + timedelta(hours=sla_hours),
                    event.occurred_at,
                    event.correlation_id,
                    opportunity["id"],
                    self._tenant_id,
                ),
            )
            context_ref = self._build_context(
                connection, opportunity["id"], deal, event.correlation_id
            )
            return PipelineResult(
                event_id=event.id,
                signal_ids=signal_ids,
                opportunity_id=opportunity["id"],
                context_ref=context_ref,
            )

    def _upsert_deal(
        self, connection: psycopg.Connection[Any], event: CanonicalEvent
    ) -> dict[str, Any]:
        data = event.data
        row = connection.execute(
            """
            insert into public.deals (
              tenant_id, title, external_id, external_stage, status, value, currency,
              source_authority, external_ref, last_activity_at
            ) values (%s, %s, %s, %s, %s, %s, %s, 'external', %s, %s)
            on conflict (tenant_id, external_id) where external_id is not null
            do update set title = excluded.title, external_stage = excluded.external_stage,
              status = excluded.status, value = excluded.value, currency = excluded.currency,
              external_ref = excluded.external_ref, last_activity_at = excluded.last_activity_at,
              updated_at = now(), version = public.deals.version + 1
            returning id, title, external_id, external_stage, status, value, currency,
                      owner_user_id, last_activity_at
            """,
            (
                self._tenant_id,
                str(data.get("title") or f"Negócio {event.aggregate_id}"),
                event.aggregate_id,
                data.get("stage"),
                data.get("status") if data.get("status") in {"open", "won", "lost"} else "open",
                float(data.get("value") or 0),
                str(data.get("currency") or "BRL"),
                Jsonb({"provider": "fake-crm", "id": event.aggregate_id}),
                event.occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("deal_upsert_failed")
        return dict(row)

    def _get_or_create_opportunity(
        self, connection: psycopg.Connection[Any], deal: dict[str, Any], event: CanonicalEvent
    ) -> tuple[dict[str, Any], bool]:
        existing = connection.execute(
            """
            select id, state from public.ares_opportunities
            where tenant_id = %s and deal_id = %s and opportunity_type = 'revenue_recovery'
              and state <> 'closed'
            """,
            (self._tenant_id, deal["id"]),
        ).fetchone()
        if existing is not None:
            return dict(existing), False
        created = connection.execute(
            """
            insert into public.ares_opportunities (
              tenant_id, deal_id, opportunity_type, state, correlation_id,
              last_activity_at, primary_signal_type
            ) values (%s, %s, 'revenue_recovery', 'prioritized', %s, %s, 'pending')
            returning id, state
            """,
            (self._tenant_id, deal["id"], event.correlation_id, event.occurred_at),
        ).fetchone()
        if created is None:
            raise RuntimeError("opportunity_insert_failed")
        return dict(created), True

    def _record_initial_transitions(
        self, connection: psycopg.Connection[Any], opportunity_id: UUID, event: CanonicalEvent
    ) -> None:
        for from_state, to_state, reason in (
            (None, "detected", "first_signal_detected"),
            ("detected", "prioritized", "deterministic_score_available"),
        ):
            connection.execute(
                """
                insert into public.opportunity_state_transitions (
                  tenant_id, opportunity_id, from_state, to_state, reason,
                  evidence_event_id, correlation_id, actor_type, actor_id, source
                ) values (%s, %s, %s, %s, %s, %s, %s, 'system', 'opportunity-engine:m2.1', 'ares')
                """,
                (
                    self._tenant_id,
                    opportunity_id,
                    from_state,
                    to_state,
                    reason,
                    event.id,
                    event.correlation_id,
                ),
            )

    def _build_context(
        self,
        connection: psycopg.Connection[Any],
        opportunity_id: UUID,
        deal: dict[str, Any],
        correlation_id: UUID,
    ) -> UUID:
        events = connection.execute(
            """
            select id, event_type, occurred_at, data, source, source_ref
            from public.commercial_events
            where tenant_id = %s and aggregate_type = 'deal' and aggregate_id = %s
            order by occurred_at desc, id desc limit 100
            """,
            (self._tenant_id, deal["external_id"]),
        ).fetchall()
        signals = connection.execute(
            """
            select id, event_id, signal_type, rule_id, rule_version, severity, evidence, detected_at
            from public.signals
            where tenant_id = %s and opportunity_id = %s
            order by severity desc, detected_at desc, id
            """,
            (self._tenant_id, opportunity_id),
        ).fetchall()
        selected = [dict(row) for row in events]
        truncated = False
        while True:
            facts = {
                "deal": {
                    key: deal.get(key)
                    for key in (
                        "id",
                        "title",
                        "external_id",
                        "external_stage",
                        "status",
                        "value",
                        "currency",
                    )
                },
                "signals": [dict(row) for row in signals],
                "events": selected,
            }
            token_estimate = math.ceil(len(json.dumps(facts, default=str, ensure_ascii=False)) / 4)
            if token_estimate <= CONTEXT_TOKEN_LIMIT or not selected:
                break
            selected.pop()
            truncated = True
        citations = [
            {
                "event_id": str(row["id"]),
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"].isoformat(),
                "source": row["source"],
                "source_ref": row["source_ref"],
            }
            for row in selected
        ]
        content_hash = _canonical_hash({"facts": facts, "citations": citations})
        existing = connection.execute(
            """
            select id from public.context_snapshots
            where tenant_id = %s and opportunity_id = %s and content_hash = %s
            """,
            (self._tenant_id, opportunity_id, content_hash),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        version_row = connection.execute(
            """
            select coalesce(max(snapshot_version), 0) + 1 as next_version
            from public.context_snapshots where tenant_id = %s and opportunity_id = %s
            """,
            (self._tenant_id, opportunity_id),
        ).fetchone()
        row = connection.execute(
            """
            insert into public.context_snapshots (
              tenant_id, opportunity_id, snapshot_version, opportunity_state,
              facts_json, citations_json, token_estimate, content_hash, source,
              source_ref, truncated, included_event_count, omitted_event_count, correlation_id
            ) values (%s, %s, %s, 'prioritized', %s, %s, %s, %s, 'ares', %s, %s, %s, %s, %s)
            returning id
            """,
            (
                self._tenant_id,
                opportunity_id,
                int(version_row["next_version"] if version_row else 1),
                Jsonb(_jsonable(facts)),
                Jsonb(citations),
                token_estimate,
                content_hash,
                "context-builder:m2.1",
                truncated,
                len(selected),
                len(events) - len(selected),
                correlation_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("context_snapshot_insert_failed")
        return row["id"]

    async def list_opportunities(
        self,
        *,
        state: str | None = None,
        owner: UUID | None = None,
        min_score: float | None = None,
        sla_before: datetime | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._list_opportunities_sync,
            state,
            owner,
            min_score,
            sla_before,
            cursor,
            limit,
        )

    def _list_opportunities_sync(
        self,
        state: str | None,
        owner: UUID | None,
        min_score: float | None,
        sla_before: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any]:
        clauses = ["o.tenant_id = %s"]
        params: list[Any] = [self._tenant_id]
        for clause, value in (
            ("o.state = %s", state),
            ("o.owner_user_id = %s", owner),
            ("o.score >= %s", min_score),
            ("o.sla_at <= %s", sla_before),
        ):
            if value is not None:
                clauses.append(clause)
                params.append(value)
        if cursor:
            decoded = _cursor_decode(cursor)
            clauses.append(
                "(o.priority, coalesce(o.sla_at, 'infinity'), -o.score, o.id) > (%s, %s, %s, %s)"
            )
            params.extend([decoded[0], decoded[1], decoded[2], decoded[3]])
        params.append(limit + 1)
        query = f"""
            select o.id, o.opportunity_type, o.state, o.score, o.priority,
              o.owner_user_id, o.sla_at, o.opened_at, o.updated_at, o.version,
              o.signal_count, o.primary_signal_type, o.score_version, o.score_breakdown,
              o.correlation_id, d.id as deal_id, d.title, d.external_id, d.external_stage,
              d.value as deal_value, d.currency, d.last_activity_at
            from public.ares_opportunities o
            join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id
            where {" and ".join(clauses)}
            order by o.priority, o.sla_at asc nulls last, o.score desc, o.id
            limit %s
        """
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = [dict(row) for row in connection.execute(query, params).fetchall()]
        has_more = len(rows) > limit
        items = rows[:limit]
        return {
            "items": items,
            "next_cursor": _cursor_encode(items[-1]) if has_more and items else None,
            "source": "ARES Core / Supabase local",
            "freshness_at": datetime.now(UTC),
        }

    async def get_opportunity(self, opportunity_id: UUID) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_opportunity_sync, opportunity_id)

    def _get_opportunity_sync(self, opportunity_id: UUID) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            opportunity = connection.execute(
                """
                select o.*, d.title, d.external_id, d.external_stage, d.status as deal_status,
                  d.value as deal_value, d.currency, d.external_ref
                from public.ares_opportunities o
                join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id
                where o.tenant_id = %s and o.id = %s
                """,
                (self._tenant_id, opportunity_id),
            ).fetchone()
            if opportunity is None:
                return None
            signals = connection.execute(
                """
                select s.*, e.event_type, e.occurred_at as evidence_occurred_at,
                  e.source_ref as evidence_source_ref, e.data as event_data
                from public.signals s join public.commercial_events e
                  on e.tenant_id = s.tenant_id and e.id = s.event_id
                where s.tenant_id = %s and s.opportunity_id = %s
                order by s.severity desc, s.detected_at desc
                """,
                (self._tenant_id, opportunity_id),
            ).fetchall()
            transitions = connection.execute(
                """
                select * from public.opportunity_state_transitions
                where tenant_id = %s and opportunity_id = %s
                order by occurred_at, id
                """,
                (self._tenant_id, opportunity_id),
            ).fetchall()
        return {
            "opportunity": dict(opportunity),
            "evidence": [dict(row) for row in signals],
            "timeline": [dict(row) for row in transitions],
            "recommendation": None,
            "recommendation_status": "planned_for_m3",
        }

    async def get_context(self, opportunity_id: UUID) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_context_sync, opportunity_id)

    def _get_context_sync(self, opportunity_id: UUID) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                select id as context_ref, snapshot_version, opportunity_state, facts_json as facts,
                  citations_json as citations, token_estimate, content_hash, source, source_ref,
                  captured_at, truncated, included_event_count, omitted_event_count, correlation_id
                from public.context_snapshots
                where tenant_id = %s and opportunity_id = %s
                order by snapshot_version desc limit 1
                """,
                (self._tenant_id, opportunity_id),
            ).fetchone()
        return dict(row) if row else None
