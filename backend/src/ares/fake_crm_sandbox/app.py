import asyncio
import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ares.fake_crm_sandbox.models import (
    AddNoteRequest,
    CreateTaskRequest,
    UpdateStageRequest,
    WebhookFixtureRequest,
)
from ares.fake_crm_sandbox.seed import STAGES
from ares.fake_crm_sandbox.store import SandboxConflict, SandboxNotFound, SandboxStore

API_KEY = os.getenv("FAKE_CRM_SANDBOX_API_KEY", "local-sandbox-key")
WEBHOOK_SECRET = os.getenv("FAKE_CRM_SANDBOX_WEBHOOK_SECRET", "local-dev-only-change-me")
bearer = HTTPBearer(auto_error=False)
store = SandboxStore()

app = FastAPI(
    title="ARES FakeCRM HTTP Sandbox",
    version="0.1.0",
    description="CRM fictício, determinístico e sem dados pessoais reais.",
    redoc_url=None,
)


@app.middleware("http")
async def add_request_identity(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["X-Provider-Request-Id"] = str(uuid4())
    correlation_id = request.headers.get("X-Correlation-Id")
    if correlation_id:
        response.headers["X-Correlation-Id"] = correlation_id
    return response


async def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if credentials is None or not hmac.compare_digest(credentials.credentials, API_KEY):
        raise HTTPException(status_code=401, detail={"code": "invalid_api_key"})


Authorized = Annotated[None, Depends(require_api_key)]


async def simulate_fault(x_fakecrm_scenario: str | None = Header(default=None)) -> None:
    if x_fakecrm_scenario is None:
        return
    faults = {
        "unauthorized": (401, "simulated_unauthorized"),
        "not_found": (404, "simulated_not_found"),
        "conflict": (409, "simulated_conflict"),
        "rate_limit": (429, "simulated_rate_limit"),
        "server_error": (500, "simulated_server_error"),
    }
    if x_fakecrm_scenario == "timeout":
        await asyncio.sleep(3)
        return
    fault = faults.get(x_fakecrm_scenario)
    if fault is not None:
        headers = {"Retry-After": "1"} if fault[0] == 429 else None
        raise HTTPException(status_code=fault[0], detail={"code": fault[1]}, headers=headers)


Fault = Annotated[None, Depends(simulate_fault)]


def require_idempotency(idempotency_key: str | None = Header(default=None)) -> str:
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "idempotency_key_required"})
    return idempotency_key


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "fake-crm-sandbox", "synthetic": True}


@app.get("/v1/capabilities")
async def capabilities(_auth: Authorized, _fault: Fault) -> dict[str, bool]:
    return {
        "read_deals": True,
        "describe_schema": True,
        "read_changes": True,
        "create_task": True,
        "add_note": True,
        "update_stage": True,
        "signed_webhooks": True,
    }


@app.get("/v1/schema")
async def schema(_auth: Authorized, _fault: Fault) -> dict[str, Any]:
    return {
        "provider": "fake-crm-http",
        "synthetic": True,
        "entities": ["company", "contact", "deal", "activity", "task", "note"],
        "deal_fields": [
            "id",
            "title",
            "stage",
            "value",
            "currency",
            "version",
            "changed_at",
            "owner_id",
        ],
    }


@app.get("/v1/stages")
async def list_stages(_auth: Authorized, _fault: Fault) -> dict[str, Any]:
    return {"items": [{"id": item, "label": item.replace("_", " ").title()} for item in STAGES]}


@app.get("/v1/deals")
async def list_deals(
    _auth: Authorized,
    _fault: Fault,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    changed_after: datetime | None = None,
) -> dict[str, Any]:
    try:
        items, next_cursor, watermark = store.list_deals(cursor, limit, changed_after)
    except SandboxConflict as error:
        raise HTTPException(status_code=400, detail={"code": str(error)}) from error
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "next_cursor": next_cursor,
        "watermark": watermark,
    }


@app.get("/v1/contacts")
async def list_contacts(_auth: Authorized, _fault: Fault) -> dict[str, Any]:
    return {"items": store.contacts}


@app.get("/v1/deals/{deal_id}")
async def get_deal(deal_id: str, _auth: Authorized, _fault: Fault) -> dict[str, Any]:
    try:
        return store.get_deal(deal_id).model_dump(mode="json")
    except SandboxNotFound as error:
        raise HTTPException(status_code=404, detail={"code": "deal_not_found"}) from error


@app.get("/v1/activities")
async def list_activities(_auth: Authorized, _fault: Fault) -> dict[str, Any]:
    return {"items": store.activities}


@app.post("/v1/deals/{deal_id}/tasks")
async def create_task(
    deal_id: str,
    payload: CreateTaskRequest,
    _auth: Authorized,
    _fault: Fault,
    idempotency_key: Annotated[str, Depends(require_idempotency)],
) -> dict[str, Any]:
    return _write(lambda: store.write("task", deal_id, payload.title, idempotency_key))


@app.post("/v1/deals/{deal_id}/notes")
async def add_note(
    deal_id: str,
    payload: AddNoteRequest,
    _auth: Authorized,
    _fault: Fault,
    idempotency_key: Annotated[str, Depends(require_idempotency)],
) -> dict[str, Any]:
    return _write(lambda: store.write("note", deal_id, payload.body, idempotency_key))


@app.patch("/v1/deals/{deal_id}/stage")
async def update_stage(
    deal_id: str,
    payload: UpdateStageRequest,
    _auth: Authorized,
    _fault: Fault,
    idempotency_key: Annotated[str, Depends(require_idempotency)],
) -> dict[str, Any]:
    return _write(
        lambda: store.update_stage(
            deal_id,
            payload.stage,
            payload.expected_version,
            idempotency_key,
        )
    )


@app.post("/v1/admin/reset")
async def reset(_auth: Authorized) -> dict[str, Any]:
    return {"reset": True, "synthetic": True, "counts": store.reset()}


@app.get("/v1/admin/state")
async def state(_auth: Authorized) -> dict[str, Any]:
    return {"synthetic": True, "counts": store.counts()}


@app.post("/v1/admin/events")
async def webhook_fixture(payload: WebhookFixtureRequest, _auth: Authorized) -> dict[str, Any]:
    deal = store.deals.get(payload.deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail={"code": "deal_not_found"})
    event = {
        "provider_event_id": f"fake-http-{uuid4()}",
        "event_type": payload.event_type,
        "aggregate_type": "deal",
        "aggregate_id": deal.id,
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {**deal.model_dump(mode="json"), **payload.data, "fixture": True},
    }
    raw_body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return {
        "raw_body_base64": base64.b64encode(raw_body).decode(),
        "signature": f"sha256={digest}",
        "event": event,
    }


def _write(operation: Any) -> dict[str, Any]:
    try:
        return operation().model_dump(mode="json")
    except SandboxNotFound as error:
        raise HTTPException(status_code=404, detail={"code": "deal_not_found"}) from error
    except SandboxConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": str(error)},
        ) from error
