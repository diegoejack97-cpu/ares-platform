import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ares.agents.api import agent_router
from ares.auth.models import AuthenticatedUser
from ares.auth.service import SupabaseAuthService
from ares.chat.api import chat_router
from ares.command_center.api import command_center_router
from ares.config import get_settings
from ares.connectors.fake_crm import FakeCRMProvider
from ares.connectors.fake_crm_lab import FakeCRMLabClient
from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.connectors.provider import CRMProvider
from ares.decision.models import DecideCommand
from ares.decision.service import DecisionConflict, DecisionService
from ares.event_journal.models import AcceptedEvent, IncomingCRMEvent, JournalPage
from ares.event_journal.service import EventJournal, InMemoryEventJournal, PostgresEventJournal
from ares.graph.api import graph_router
from ares.impact.api import impact_router
from ares.integrations.api import integration_router
from ares.intelligence.service import IntelligenceService
from ares.leads.api import lead_router
from ares.provider.account import account_router
from ares.provider.api import install_provider_api
from ares.provider.billing import billing_status
from ares.workers.tick import TickWorker

settings = get_settings()
journal: EventJournal
if settings.event_journal_backend == "memory":
    journal = InMemoryEventJournal()
    intelligence: IntelligenceService | None = None
else:
    journal = PostgresEventJournal(settings.database_url, settings.tenant_id)
    intelligence = IntelligenceService(settings.database_url, settings.tenant_id)
fake_crm = FakeCRMProvider(settings.fake_crm_webhook_secret)
crm_provider: CRMProvider
if settings.crm_provider == "http_fake":
    crm_provider = FakeCRMHTTPProvider(
        settings.fake_crm_base_url,
        settings.fake_crm_api_key.get_secret_value(),
        settings.fake_crm_timeout_seconds,
    )
else:
    crm_provider = fake_crm
auth_service = SupabaseAuthService(
    settings.supabase_url,
    settings.supabase_publishable_key,
    settings.database_url,
)
bearer = HTTPBearer(auto_error=False)
fake_crm_lab = FakeCRMLabClient(
    settings.fake_crm_base_url,
    settings.fake_crm_api_key.get_secret_value(),
    settings.fake_crm_timeout_seconds,
)

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
    allow_methods=["GET", "POST", "PUT", "PATCH"],
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
    data: dict[str, Any] | None = None


class TickResponse(BaseModel):
    acquired: bool
    claimed: int
    succeeded: int
    failed: int


class LabTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)


class LabNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class LabStageRequest(BaseModel):
    stage: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required"
        )
    user = await auth_service.authenticate(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        billing = await asyncio.to_thread(billing_status, settings.database_url, user.tenant_id)
        if billing["degraded"]:
            raise HTTPException(
                403,
                detail={
                    "code": "billing_degraded",
                    "message": "Prazo encerrado. Leitura e histórico continuam disponíveis.",
                    "correlation_id": str(uuid4()),
                },
            )
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(require_user)]

app.include_router(integration_router(settings, require_user))
app.include_router(agent_router(settings, require_user))
app.include_router(graph_router(settings, require_user))
app.include_router(chat_router(settings, require_user))
app.include_router(impact_router(settings, require_user))
app.include_router(command_center_router(settings, require_user))
app.include_router(lead_router(settings, require_user))
install_provider_api(app, settings)
app.include_router(account_router(settings, require_user))


@app.get("/api/v1/account/billing")
async def account_billing(user: CurrentUser) -> Any:
    return await asyncio.to_thread(billing_status, settings.database_url, user.tenant_id)


def require_development() -> None:
    if settings.environment != "development":
        raise HTTPException(status_code=404, detail="not_found")


def get_fake_crm_lab() -> FakeCRMLabClient:
    return fake_crm_lab


DevelopmentOnly = Annotated[None, Depends(require_development)]
FakeCRMLab = Annotated[FakeCRMLabClient, Depends(get_fake_crm_lab)]


def require_lab_admin(user: CurrentUser) -> AuthenticatedUser:
    if user.role != "admin" or user.tenant_id != settings.tenant_id:
        raise HTTPException(status_code=403, detail="admin_required")
    return user


LabAdmin = Annotated[AuthenticatedUser, Depends(require_lab_admin)]


def decisions_for(user: AuthenticatedUser) -> DecisionService:
    return DecisionService(
        settings.database_url,
        user.tenant_id,
        crm_provider,
        openai_api_key=settings.openai_api_key.get_secret_value(),
        openai_model=settings.openai_model,
        estimated_cost_usd=Decimal(str(settings.recommendation_estimated_cost_usd)),
    )


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
    scoped = (
        journal
        if _user.tenant_id == settings.tenant_id
        else PostgresEventJournal(settings.database_url, _user.tenant_id)
    )
    return await scoped.list_events()


@app.post(
    "/api/v1/dev/fake-crm/events",
    response_model=AcceptedEvent,
    status_code=status.HTTP_202_ACCEPTED,
)
async def simulate_fake_crm_event(
    payload: SimulateEventRequest, _user: CurrentUser
) -> AcceptedEvent:
    require_development()
    require_lab_admin(_user)
    aggregate_id = payload.aggregate_id or f"deal-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    fixture: dict[str, Any] = {
        "title": "Expansão Serra Metais — Unidade Sul",
        "stage": "proposal",
        "previous_stage": "negotiation",
        "status": "open",
        "risk": "follow_up_overdue",
        "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
        "days_in_stage": 12,
        "next_step": None,
        "owner_id": None,
        "value": 125000,
        "currency": "BRL",
        "days_since_contact": 14,
        "expected_close_at": (now + timedelta(days=3)).isoformat(),
        "fixture": True,
    }
    fixture.update(payload.data or {})
    incoming = IncomingCRMEvent(
        provider_event_id=f"fake-{uuid4()}",
        event_type=payload.event_type,
        aggregate_type=payload.aggregate_type,
        aggregate_id=aggregate_id,
        occurred_at=now,
        data=fixture,
    )
    raw_body = json.dumps(incoming.model_dump(mode="json"), separators=(",", ":")).encode()
    normalized = fake_crm.verify_and_normalize(raw_body, fake_crm.sign(raw_body))
    accepted = await journal.record(normalized)
    if intelligence is not None:
        await intelligence.process_event(accepted.event_id)
    return accepted


@app.get("/api/v1/dev/fake-crm/lab")
async def get_fake_crm_lab_snapshot(
    _user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
) -> dict[str, Any]:
    try:
        return await client.snapshot()
    except CRMProviderRequestError as error:
        raise HTTPException(
            status_code=502,
            detail={"code": error.code, "upstream_status": error.status_code},
        ) from error


@app.post("/api/v1/dev/fake-crm/lab/reset")
async def reset_fake_crm_lab(
    _user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
) -> dict[str, Any]:
    try:
        return await client.reset()
    except CRMProviderRequestError as error:
        raise HTTPException(status_code=502, detail={"code": error.code}) from error


@app.post("/api/v1/dev/fake-crm/lab/deals/{deal_id}/tasks")
async def create_fake_crm_lab_task(
    deal_id: str,
    payload: LabTaskRequest,
    _user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    try:
        return await client.create_task(deal_id, payload.title, idempotency_key)
    except CRMProviderRequestError as error:
        raise HTTPException(
            status_code=error.status_code or 502,
            detail={"code": error.code},
        ) from error


@app.post("/api/v1/dev/fake-crm/lab/deals/{deal_id}/notes")
async def add_fake_crm_lab_note(
    deal_id: str,
    payload: LabNoteRequest,
    _user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    try:
        return await client.add_note(deal_id, payload.body, idempotency_key)
    except CRMProviderRequestError as error:
        raise HTTPException(
            status_code=error.status_code or 502,
            detail={"code": error.code},
        ) from error


@app.patch("/api/v1/dev/fake-crm/lab/deals/{deal_id}/stage")
async def update_fake_crm_lab_stage(
    deal_id: str,
    payload: LabStageRequest,
    _user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    try:
        return await client.update_stage(
            deal_id,
            payload.stage,
            payload.expected_version,
            idempotency_key,
        )
    except CRMProviderRequestError as error:
        raise HTTPException(
            status_code=error.status_code or 502,
            detail={"code": error.code},
        ) from error


@app.post("/api/v1/dev/fake-crm/lab/deals/{deal_id}/events", response_model=AcceptedEvent)
async def send_fake_crm_lab_event(
    deal_id: str,
    user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
) -> AcceptedEvent:
    try:
        deal = await client.get_deal(deal_id)
    except CRMProviderRequestError as error:
        raise HTTPException(
            status_code=error.status_code or 502,
            detail={"code": error.code},
        ) from error
    return await simulate_fake_crm_event(
        SimulateEventRequest(aggregate_id=deal_id, data=deal),
        user,
    )


@app.post("/api/v1/dev/fake-crm/lab/faults/{scenario}")
async def test_fake_crm_lab_fault(
    scenario: str,
    _user: LabAdmin,
    _development: DevelopmentOnly,
    client: FakeCRMLab,
) -> dict[str, Any]:
    allowed = {"unauthorized", "not_found", "conflict", "rate_limit", "server_error", "timeout"}
    if scenario not in allowed:
        raise HTTPException(status_code=422, detail={"code": "unknown_scenario"})
    return await client.simulate_fault(scenario)


@app.get("/api/v1/opportunities/analytics")
async def opportunity_analytics(user: CurrentUser) -> dict[str, Any]:
    """Aggregates over every opportunity, so charts and agents share one population."""
    service = (
        intelligence
        if intelligence is not None and user.tenant_id == settings.tenant_id
        else IntelligenceService(settings.database_url, user.tenant_id)
    )
    return await service.opportunity_analytics()


@app.get("/api/v1/opportunities")
async def list_opportunities(
    user: CurrentUser,
    state_filter: str | None = Query(default=None, alias="state"),
    owner: UUID | None = None,
    min_score: float | None = Query(default=None, ge=0, le=1),
    sla_before: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    service = (
        intelligence
        if intelligence is not None and user.tenant_id == settings.tenant_id
        else IntelligenceService(settings.database_url, user.tenant_id)
    )
    try:
        return await service.list_opportunities(
            state=state_filter,
            owner=owner,
            min_score=min_score,
            sla_before=sla_before,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/v1/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: UUID, user: CurrentUser) -> dict[str, Any]:
    service = (
        intelligence
        if intelligence is not None and user.tenant_id == settings.tenant_id
        else IntelligenceService(settings.database_url, user.tenant_id)
    )
    result = await service.get_opportunity(opportunity_id)
    if result is None:
        raise HTTPException(status_code=404, detail="opportunity_not_found")
    recommendation = await decisions_for(user).get_latest_for_opportunity(opportunity_id)
    result["recommendation"] = recommendation
    result["recommendation_status"] = (
        recommendation["status"] if recommendation else "not_generated"
    )
    return result


@app.post(
    "/api/v1/opportunities/{opportunity_id}/recommendations",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_recommendation(
    opportunity_id: UUID,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if user.tenant_id != settings.tenant_id:
        raise HTTPException(503, detail={"code": "tenant_crm_adapter_not_configured"})
    try:
        result = await decisions_for(user).create_recommendation(opportunity_id)
        if result.get("intent_id"):
            worker = TickWorker(
                settings.database_url,
                settings.supabase_url,
                settings.supabase_secret_key.get_secret_value(),
                provider=crm_provider,
            )
            background_tasks.add_task(worker.run_once)
        return result
    except DecisionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "current_version": error.current_version},
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/v1/recommendations/{recommendation_id}")
async def get_recommendation(recommendation_id: UUID, user: CurrentUser) -> dict[str, Any]:
    result = await decisions_for(user).get_recommendation(recommendation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="recommendation_not_found")
    return result


@app.post("/api/v1/recommendations/{recommendation_id}/decide")
async def decide_recommendation(
    recommendation_id: UUID,
    command: DecideCommand,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if user.tenant_id != settings.tenant_id:
        raise HTTPException(503, detail={"code": "tenant_crm_adapter_not_configured"})
    try:
        result = await decisions_for(user).decide(recommendation_id, command, str(user.user_id))
        if result.get("intent_id"):
            worker = TickWorker(
                settings.database_url,
                settings.supabase_url,
                settings.supabase_secret_key.get_secret_value(),
                provider=crm_provider,
            )
            background_tasks.add_task(worker.run_once)
        return result
    except DecisionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "current_version": error.current_version},
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/v1/approvals")
async def list_approvals(user: CurrentUser) -> dict[str, Any]:
    return await decisions_for(user).list_approvals()


@app.get("/api/v1/actions/{intent_id}")
async def get_action(intent_id: UUID, user: CurrentUser) -> dict[str, Any]:
    result = await decisions_for(user).get_action(intent_id)
    if result is None:
        raise HTTPException(status_code=404, detail="action_intent_not_found")
    return result


@app.get("/api/v1/opportunities/{opportunity_id}/context")
async def get_opportunity_context(opportunity_id: UUID, user: CurrentUser) -> dict[str, Any]:
    service = (
        intelligence
        if intelligence is not None and user.tenant_id == settings.tenant_id
        else IntelligenceService(settings.database_url, user.tenant_id)
    )
    result = await service.get_context(opportunity_id)
    if result is None:
        raise HTTPException(status_code=404, detail="opportunity_context_not_found")
    return result


@app.post("/api/v1/internal/tick", response_model=TickResponse)
async def run_tick(x_ares_tick_secret: str | None = Header(default=None)) -> TickResponse:
    expected = settings.tick_secret.get_secret_value()
    if x_ares_tick_secret is None or not secrets.compare_digest(x_ares_tick_secret, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_tick_secret")
    worker = TickWorker(
        settings.database_url,
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
        provider=crm_provider,
    )
    result = await asyncio.to_thread(worker.run_once)
    return TickResponse(
        acquired=result.acquired,
        claimed=result.claimed,
        succeeded=result.succeeded,
        failed=result.failed,
    )
