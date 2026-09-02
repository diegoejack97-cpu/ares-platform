import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest

from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import PostgresEventJournal
from ares.intelligence.service import CONTEXT_TOKEN_LIMIT, IntelligenceService

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
@pytest.mark.asyncio
async def test_m2_pipeline_is_idempotent_explainable_and_queryable() -> None:
    assert DATABASE_URL is not None
    now = datetime.now(UTC)
    journal = PostgresEventJournal(DATABASE_URL, TENANT_ID)
    service = IntelligenceService(DATABASE_URL, TENANT_ID)
    event = IncomingCRMEvent(
        provider_event_id="m2-postgres-integration-1",
        event_type="deal.updated",
        aggregate_type="deal",
        aggregate_id="deal-m2-integration",
        occurred_at=now,
        data={
            "title": "Integração M2",
            "stage": "proposal",
            "previous_stage": "negotiation",
            "risk": "follow_up_overdue",
            "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
            "days_in_stage": 12,
            "next_step": None,
            "owner_id": None,
            "value": 125_000,
            "currency": "BRL",
            "days_since_contact": 14,
            "expected_close_at": (now + timedelta(days=3)).isoformat(),
        },
    )
    accepted = await journal.record(event)
    first = await service.process_event(accepted.event_id)
    replay = await service.process_event(accepted.event_id)

    assert len(first.signal_ids) == 8
    assert replay.opportunity_id == first.opportunity_id
    assert replay.context_ref == first.context_ref
    assert first.opportunity_id is not None

    page = await service.list_opportunities(min_score=0.8)
    row = next(row for row in page["items"] if row["id"] == first.opportunity_id)
    assert row["version"] == 2
    detail = await service.get_opportunity(first.opportunity_id)
    context = await service.get_context(first.opportunity_id)
    assert detail is not None and len(detail["evidence"]) == 8
    assert detail["recommendation"] is None
    assert context is not None
    assert context["token_estimate"] <= CONTEXT_TOKEN_LIMIT
    assert context["citations"] and len(context["content_hash"]) == 64

    with psycopg.connect(DATABASE_URL) as connection:
        counts = connection.execute(
            """
            select
              (select count(*) from public.signals where tenant_id = %s and opportunity_id = %s),
              (select count(*) from public.ares_opportunities where tenant_id = %s and id = %s),
              (select count(*) from public.context_snapshots
                 where tenant_id = %s and opportunity_id = %s)
            """,
            (
                TENANT_ID,
                first.opportunity_id,
                TENANT_ID,
                first.opportunity_id,
                TENANT_ID,
                first.opportunity_id,
            ),
        ).fetchone()
        assert counts == (8, 1, 1)
