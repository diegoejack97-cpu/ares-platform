import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ares.config import get_settings
from ares.connectors.fake_crm import FakeCRMProvider
from ares.event_journal.models import AcceptedEvent, IncomingCRMEvent, JournalPage
from ares.event_journal.service import InMemoryEventJournal

settings = get_settings()
journal = InMemoryEventJournal()
fake_crm = FakeCRMProvider(settings.fake_crm_webhook_secret)

app = FastAPI(
    title="ARES Platform API",
    version="0.1.0",
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-FakeCRM-Signature", "X-Correlation-Id"],
)


class HealthResponse(BaseModel):
    status: str
    service: str


class SimulateEventRequest(BaseModel):
    event_type: str = "deal.updated"
    aggregate_type: str = "deal"
    aggregate_id: str | None = None


@app.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok", service="ares-api")


@app.post(
    "/api/v1/webhooks/fake-crm/{connection_id}",
    response_model=AcceptedEvent,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_fake_crm_webhook(
    connection_id: UUID,
    request: Request,
    x_fakecrm_signature: str | None = Header(default=None),
) -> AcceptedEvent:
    del connection_id
    raw_body = await request.body()
    incoming = fake_crm.verify_and_normalize(raw_body, x_fakecrm_signature)
    return await journal.record(incoming)


@app.get("/api/v1/journal/events", response_model=JournalPage)
async def list_journal_events() -> JournalPage:
    return await journal.list_events()


@app.post(
    "/api/v1/dev/fake-crm/events",
    response_model=AcceptedEvent,
    status_code=status.HTTP_202_ACCEPTED,
)
async def simulate_fake_crm_event(payload: SimulateEventRequest) -> AcceptedEvent:
    aggregate_id = payload.aggregate_id or f"deal-{uuid4().hex[:8]}"
    incoming = IncomingCRMEvent(
        provider_event_id=f"fake-{uuid4()}",
        event_type=payload.event_type,
        aggregate_type=payload.aggregate_type,  # type: ignore[arg-type]
        aggregate_id=aggregate_id,
        occurred_at=datetime.now(UTC),
        data={
            "stage": "proposal",
            "risk": "follow_up_overdue",
            "fixture": True,
        },
    )
    raw_body = json.dumps(incoming.model_dump(mode="json"), separators=(",", ":")).encode()
    normalized = fake_crm.verify_and_normalize(raw_body, fake_crm.sign(raw_body))
    return await journal.record(normalized)
