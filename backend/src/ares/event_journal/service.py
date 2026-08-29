from asyncio import Lock

from ares.event_journal.models import AcceptedEvent, IncomingCRMEvent, JournalEvent, JournalPage


class InMemoryEventJournal:
    """M1 executable slice. PostgreSQL persistence is the next adapter."""

    def __init__(self) -> None:
        self._events: dict[str, JournalEvent] = {}
        self._lock = Lock()

    async def record(self, incoming: IncomingCRMEvent) -> AcceptedEvent:
        async with self._lock:
            existing = self._events.get(incoming.provider_event_id)
            if existing is not None:
                return AcceptedEvent(
                    duplicate=True,
                    event_id=existing.id,
                    correlation_id=existing.correlation_id,
                )

            event = JournalEvent(**incoming.model_dump())
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
