import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import PostgresEventJournal

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
@pytest.mark.asyncio
async def test_postgres_journal_persists_and_deduplicates() -> None:
    assert DATABASE_URL is not None
    journal = PostgresEventJournal(
        DATABASE_URL,
        UUID("20000000-0000-0000-0000-000000000001"),
    )
    provider_event_id = f"postgres-integration-{uuid4()}"
    event = IncomingCRMEvent(
        provider_event_id=provider_event_id,
        event_type="deal.updated",
        aggregate_type="deal",
        aggregate_id="deal-postgres-42",
        occurred_at=datetime.now(UTC),
        data={"stage": "proposal", "fixture": True},
    )

    first = await journal.record(event)
    second = await journal.record(event)
    page = await journal.list_events()

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.event_id == first.event_id
    assert page.total >= 1
    assert page.source == "Supabase/PostgreSQL local"
    assert any(
        item.id == first.event_id and item.aggregate_id == "deal-postgres-42" for item in page.items
    )

    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "delete from public.commercial_events where tenant_id = %s and id = %s",
            (UUID("20000000-0000-0000-0000-000000000001"), first.event_id),
        )
