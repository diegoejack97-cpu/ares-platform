from datetime import UTC, datetime

import pytest

from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import InMemoryEventJournal


@pytest.mark.asyncio
async def test_record_is_idempotent_by_provider_event_id() -> None:
    journal = InMemoryEventJournal()
    event = IncomingCRMEvent(
        provider_event_id="fake-event-1",
        event_type="deal.updated",
        aggregate_type="deal",
        aggregate_id="deal-42",
        occurred_at=datetime.now(UTC),
        data={"stage": "proposal"},
    )

    first = await journal.record(event)
    second = await journal.record(event)
    page = await journal.list_events()

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.event_id == first.event_id
    assert page.total == 1
