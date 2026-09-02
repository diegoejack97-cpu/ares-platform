import asyncio
import hashlib
import json
from asyncio import Lock
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.event_journal.models import AcceptedEvent, IncomingCRMEvent, JournalEvent, JournalPage


class EventJournal(Protocol):
    async def record(
        self, incoming: IncomingCRMEvent, correlation_id: UUID | None = None
    ) -> AcceptedEvent: ...

    async def list_events(self) -> JournalPage: ...

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

    async def list_events(self) -> JournalPage:
        events = sorted(self._events.values(), key=lambda item: item.recorded_at, reverse=True)
        return JournalPage(items=events, total=len(events))

    async def clear(self) -> None:
        async with self._lock:
            self._events.clear()

    async def is_ready(self) -> bool:
        return True


class PostgresEventJournal:
    """Canonical Event Journal persisted in the Supabase PostgreSQL database."""

    def __init__(self, database_url: str, tenant_id: UUID) -> None:
        self._database_url = database_url
        self._tenant_id = tenant_id

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

    async def list_events(self) -> JournalPage:
        return await asyncio.to_thread(self._list_events_sync)

    def _list_events_sync(self) -> JournalPage:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                select
                  id, provider_event_id, event_type, aggregate_type, aggregate_id,
                  correlation_id, source, producer, occurred_at, recorded_at, data
                from public.commercial_events
                where tenant_id = %s
                order by recorded_at desc
                """,
                (self._tenant_id,),
            ).fetchall()
        events = [JournalEvent(status="recorded", **row) for row in rows]
        return JournalPage(items=events, total=len(events), source="Supabase/PostgreSQL local")

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
