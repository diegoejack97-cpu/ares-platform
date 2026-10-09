import asyncio
import hashlib
import json
from asyncio import Lock
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.auth.read_scope import read_connection
from ares.event_journal.models import AcceptedEvent, IncomingCRMEvent, JournalEvent, JournalPage
from ares.event_journal.pagination import decode_cursor, encode_cursor, validate_limit


class EventJournal(Protocol):
    async def record(
        self, incoming: IncomingCRMEvent, correlation_id: UUID | None = None
    ) -> AcceptedEvent: ...

    async def list_events(self, *, limit: int = 50, cursor: str | None = None) -> JournalPage: ...

    async def clear(self) -> None: ...

    async def is_ready(self) -> bool: ...


class InMemoryEventJournal:
    """Fast, isolated adapter for unit tests."""

    def __init__(self) -> None:
        self._events: dict[str, JournalEvent] = {}
        self._lock = Lock()

    async def record(
        self, incoming: IncomingCRMEvent, correlation_id: UUID | None = None
    ) -> AcceptedEvent:
        async with self._lock:
            existing = self._events.get(incoming.provider_event_id)
            if existing is not None:
                return AcceptedEvent(
                    duplicate=True,
                    event_id=existing.id,
                    correlation_id=existing.correlation_id,
                )

            event = JournalEvent(
                provider_event_id=incoming.provider_event_id,
                event_type=incoming.event_type,
                aggregate_type=incoming.aggregate_type,
                aggregate_id=incoming.aggregate_id,
                occurred_at=incoming.occurred_at,
                data=incoming.data,
                correlation_id=correlation_id or uuid4(),
            )
            self._events[incoming.provider_event_id] = event
            return AcceptedEvent(
                duplicate=False,
                event_id=event.id,
                correlation_id=event.correlation_id,
            )

    async def list_events(self, *, limit: int = 50, cursor: str | None = None) -> JournalPage:
        validate_limit(limit)
        position = decode_cursor(cursor)
        events = sorted(
            self._events.values(), key=lambda item: (item.recorded_at, item.id), reverse=True
        )
        total = len(events)
        if position is not None:
            events = [item for item in events if (item.recorded_at, item.id) < position]
        items = events[:limit]
        return JournalPage(
            items=items,
            total=total,
            next_cursor=encode_cursor(items[-1]) if len(events) > limit else None,
        )

    async def clear(self) -> None:
        async with self._lock:
            self._events.clear()

    async def is_ready(self) -> bool:
        return True


class PostgresEventJournal:
    """Canonical Event Journal persisted in the Supabase PostgreSQL database."""

    def __init__(
        self, database_url: str, tenant_id: UUID, *, reader: AuthenticatedUser | None = None
    ) -> None:
        self._database_url = database_url
        self._tenant_id = tenant_id
        self._reader = reader

    async def record(
        self, incoming: IncomingCRMEvent, correlation_id: UUID | None = None
    ) -> AcceptedEvent:
        return await asyncio.to_thread(self.record_sync, incoming, correlation_id)

    def record_sync(
        self, incoming: IncomingCRMEvent, correlation_id: UUID | None = None
    ) -> AcceptedEvent:
        event_id = uuid4()
        correlation_id = correlation_id or uuid4()
        canonical_payload = json.dumps(
            incoming.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        payload_hash = hashlib.sha256(canonical_payload).hexdigest()

        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            inserted = connection.execute(
                """
                insert into public.commercial_events (
                  id, tenant_id, event_type, event_version, producer,
                  aggregate_type, aggregate_id, provider_event_id,
                  correlation_id, actor_type, source, source_ref,
                  occurred_at, data, payload_hash
                ) values (
                  %s, %s, %s, 1, 'fake-crm',
                  %s, %s, %s,
                  %s, 'external_system', 'crm', %s,
                  %s, %s, %s
                )
                on conflict (tenant_id, producer, provider_event_id)
                  where provider_event_id is not null
                do nothing
                returning id, correlation_id
                """,
                (
                    event_id,
                    self._tenant_id,
                    incoming.event_type,
                    incoming.aggregate_type,
                    incoming.aggregate_id,
                    incoming.provider_event_id,
                    correlation_id,
                    incoming.provider_event_id,
                    incoming.occurred_at,
                    Jsonb(incoming.data),
                    payload_hash,
                ),
            ).fetchone()
            if inserted is not None:
                return AcceptedEvent(
                    duplicate=False,
                    event_id=inserted["id"],
                    correlation_id=inserted["correlation_id"],
                )

            existing = connection.execute(
                """
                select id, correlation_id
                from public.commercial_events
                where tenant_id = %s
                  and producer = 'fake-crm'
                  and provider_event_id = %s
                """,
                (self._tenant_id, incoming.provider_event_id),
            ).fetchone()
            if existing is None:
                raise RuntimeError("Event idempotency lookup failed after conflict")
            return AcceptedEvent(
                duplicate=True,
                event_id=existing["id"],
                correlation_id=existing["correlation_id"],
            )

    async def list_events(self, *, limit: int = 50, cursor: str | None = None) -> JournalPage:
        return await asyncio.to_thread(self._list_events_sync, limit, cursor)

    def _list_events_sync(self, limit: int = 50, cursor: str | None = None) -> JournalPage:
        validate_limit(limit)
        position = decode_cursor(cursor)
        with read_connection(self._database_url, self._reader) as connection:
            total = connection.execute(
                "select count(*) count from public.commercial_events where tenant_id=%s",
                (self._tenant_id,),
            ).fetchone()
            rows = connection.execute(
                """
                select
                  id, provider_event_id, event_type, aggregate_type, aggregate_id,
                  correlation_id, source, producer, occurred_at, recorded_at, data
                from public.commercial_events
                where tenant_id = %s
                  and (%s::timestamptz is null or (recorded_at,id)<(%s,%s))
                order by recorded_at desc,id desc limit %s
                """,
                (
                    self._tenant_id,
                    position[0] if position else None,
                    position[0] if position else None,
                    position[1] if position else None,
                    limit + 1,
                ),
            ).fetchall()
        events = [JournalEvent(status="recorded", **row) for row in rows[:limit]]
        return JournalPage(
            items=events,
            total=int(total["count"] if total else 0),
            next_cursor=encode_cursor(events[-1]) if len(rows) > limit else None,
            source="Supabase/PostgreSQL",
        )

    async def clear(self) -> None:
        await asyncio.to_thread(self._clear_sync)

    def _clear_sync(self) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                "delete from public.commercial_events where tenant_id = %s",
                (self._tenant_id,),
            )

    async def is_ready(self) -> bool:
        return await asyncio.to_thread(self._is_ready_sync)

    def _is_ready_sync(self) -> bool:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute("select 1").fetchone()
            return row == (1,)
        except psycopg.Error:
            return False
