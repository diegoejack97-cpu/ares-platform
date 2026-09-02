import asyncio
import json
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ares.auth.models import AuthenticatedUser
from ares.auth.service import SupabaseAuthService
from ares.config import get_settings
from ares.connectors.fake_crm import FakeCRMProvider
from ares.event_journal.models import AcceptedEvent, IncomingCRMEvent, JournalPage
from ares.event_journal.service import EventJournal, InMemoryEventJournal, PostgresEventJournal
from ares.workers.tick import TickWorker

settings = get_settings()
journal: EventJournal
if settings.event_journal_backend == "memory":
    journal = InMemoryEventJournal()
else:
    journal = PostgresEventJournal(settings.database_url, settings.tenant_id)
fake_crm = FakeCRMProvider(settings.fake_crm_webhook_secret)
auth_service = SupabaseAuthService(
    settings.supabase_url,
    settings.supabase_publishable_key,
    settings.database_url,
)
bearer = HTTPBearer(auto_error=False)

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
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-ARES-Tick-Secret",
        "X-FakeCRM-Signature",
        "X-Correlation-Id",
    ],
)


class HealthResponse(BaseModel):
    status: str
    service: str


class SimulateEventRequest(BaseModel):
    event_type: str = "deal.updated"
    aggregate_type: str = "deal"
    aggregate_id: str | None = None


class TickResponse(BaseModel):
    acquired: bool
    claimed: int
    succeeded: int
    failed: int


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required"
        )
    user = await auth_service.authenticate(credentials.credentials)
    if user is None or user.tenant_id != settings.tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(require_user)]


@app.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok", service="ares-api")


@app.get("/health/ready", response_model=HealthResponse)
async def health_ready() -> HealthResponse:
    if not await journal.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="event_journal_unavailable",
        )
    return HealthResponse(status="ready", service="ares-api")


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
async def list_journal_events(_user: CurrentUser) -> JournalPage:
    return await journal.list_events()


@app.post(
    "/api/v1/dev/fake-crm/events",
    response_model=AcceptedEvent,
    status_code=status.HTTP_202_ACCEPTED,
)
async def simulate_fake_crm_event(
    payload: SimulateEventRequest, _user: CurrentUser
) -> AcceptedEvent:
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


@app.post("/api/v1/internal/tick", response_model=TickResponse)
async def run_tick(x_ares_tick_secret: str | None = Header(default=None)) -> TickResponse:
    expected = settings.tick_secret.get_secret_value()
    if x_ares_tick_secret is None or not secrets.compare_digest(x_ares_tick_secret, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_tick_secret")
    worker = TickWorker(
        settings.database_url,
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
    )
    result = await asyncio.to_thread(worker.run_once)
    return TickResponse(
        acquired=result.acquired,
        claimed=result.claimed,
        succeeded=result.succeeded,
        failed=result.failed,
    )
