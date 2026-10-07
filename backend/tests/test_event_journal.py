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


@pytest.mark.asyncio
async def test_cursor_pages_do_not_repeat_events_with_equal_timestamps() -> None:
    journal = InMemoryEventJournal()
    for index in range(7):
        await journal.record(
            IncomingCRMEvent(
                provider_event_id=f"page-{index}",
                event_type="deal.updated",
                aggregate_type="deal",
                aggregate_id="synthetic",
                occurred_at=datetime.now(UTC),
            )
        )
    same_time = datetime.now(UTC)
    for event in journal._events.values():
        event.recorded_at = same_time
    cursor = None
    collected = []
    for expected_size in (3, 3, 1):
        page = await journal.list_events(limit=3, cursor=cursor)
        assert len(page.items) == expected_size
        assert page.total == 7
        collected.extend(item.id for item in page.items)
        cursor = page.next_cursor
    assert cursor is None
    assert len(set(collected)) == 7
    with pytest.raises(ValueError, match="invalid_cursor"):
        await journal.list_events(cursor="not-valid")
    with pytest.raises(ValueError, match="invalid_limit"):
        await journal.list_events(limit=101)
