from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ares.config import Settings
from ares.security.body_limit import BodyLimitMiddleware
from ares.security.rate_limit import RateLimited, RequestLimiter


def test_request_budget_is_shared_across_routes_but_not_users_or_companies() -> None:
    limiter = RequestLimiter(
        Settings(event_journal_backend="memory", rate_limit_requests_per_minute=2)
    )
    user, tenant = uuid4(), uuid4()
    limiter.enforce(user, tenant, "/api/v1/opportunities", "GET")
    limiter.enforce(user, tenant, "/api/v1/journal/events", "GET")
    with pytest.raises(RateLimited) as failure:
        limiter.enforce(user, tenant, "/api/v1/opportunities", "GET")
    assert 1 <= failure.value.retry_after <= 30
    limiter.enforce(uuid4(), tenant, "/api/v1/opportunities", "GET")
    limiter.enforce(user, uuid4(), "/api/v1/opportunities", "GET")


def test_chat_budget_does_not_block_reading_and_refills(monkeypatch) -> None:
    clock = [10.0]
    monkeypatch.setattr("ares.security.rate_limit.time.monotonic", lambda: clock[0])
    limiter = RequestLimiter(Settings(event_journal_backend="memory", rate_limit_chat_per_minute=1))
    user, tenant = uuid4(), uuid4()
    limiter.enforce(user, tenant, "/api/v1/chat/messages", "POST")
    with pytest.raises(RateLimited):
        limiter.enforce(user, tenant, "/api/v1/chat/messages", "POST")
    limiter.enforce(user, tenant, "/api/v1/opportunities", "GET")
    clock[0] += 60
    limiter.enforce(user, tenant, "/api/v1/chat/messages", "POST")


def test_write_budget_applies_to_all_mutations() -> None:
    limiter = RequestLimiter(
        Settings(event_journal_backend="memory", rate_limit_writes_per_minute=1)
    )
    user, tenant = uuid4(), uuid4()
    limiter.enforce(user, tenant, "/api/v1/action", "PATCH")
    with pytest.raises(RateLimited):
        limiter.enforce(user, tenant, "/api/v1/approval", "POST")


def test_body_limit_covers_content_length_and_chunked_requests() -> None:
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=32)

    @app.post("/consume")
    async def consume(request: Request):
        return {"length": len(await request.body())}

    client = TestClient(app)
    assert client.post("/consume", content=b"a" * 32).json() == {"length": 32}
    assert client.post("/consume", content=b"a" * 33).status_code == 413
    response = client.post("/consume", content=iter([b"a" * 20, b"b" * 20]))
    assert response.status_code == 413


def test_unsigned_webhook_does_not_read_request_body(monkeypatch) -> None:
    import ares.api.app as api

    async def forbidden_read(self):
        raise AssertionError("Unsigned webhook body was read")

    monkeypatch.setattr(Request, "body", forbidden_read)
    response = TestClient(api.app).post(f"/api/v1/webhooks/fake-crm/{uuid4()}", content=b"payload")
    assert response.status_code == 401


def test_authenticated_limit_returns_retry_after_and_correlation(monkeypatch) -> None:
    import ares.api.app as api
    from ares.auth.models import AuthenticatedUser

    user = AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role="seller")

    async def authenticate(token):
        return user

    monkeypatch.setattr(api.auth_service, "authenticate", authenticate)
    limiter = RequestLimiter(
        Settings(event_journal_backend="memory", rate_limit_requests_per_minute=1)
    )
    limiter.enforce(user.user_id, user.tenant_id, "/api/v1/account/billing", "GET")
    monkeypatch.setattr(api, "request_limiter", limiter)
    response = TestClient(api.app).get(
        "/api/v1/account/billing", headers={"Authorization": "Bearer synthetic"}
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["detail"]["correlation_id"] == response.headers["X-Correlation-Id"]
    assert response.headers["Cache-Control"] == "no-store"


def test_traffic_guard_precedes_auth_and_ignores_spoofed_forwarded_for() -> None:
    from ares.security.traffic_limit import TrafficLimitMiddleware

    app = FastAPI()
    app.add_middleware(TrafficLimitMiddleware, requests_per_minute=1)
    called = []

    @app.get("/api/v1/example")
    async def endpoint():
        called.append(True)
        return {"ok": True}

    client = TestClient(app)
    assert (
        client.get("/api/v1/example", headers={"X-Forwarded-For": "192.0.2.1"}).status_code == 200
    )
    response = client.get("/api/v1/example", headers={"X-Forwarded-For": "192.0.2.2"})
    assert response.status_code == 429
    assert len(called) == 1
