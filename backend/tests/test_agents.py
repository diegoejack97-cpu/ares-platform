from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from ares.agents.service import AgentAccessDenied, AgentTransparencyService
from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser


@pytest.fixture(autouse=True)
def clean_auth():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def user(role="manager"):
    return AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role=role)


def test_agent_api_requires_authentication():
    assert TestClient(app).get("/api/v1/agents").status_code == 401


def test_seller_is_denied_before_database_access():
    app.dependency_overrides[require_user] = lambda: user("seller")
    response = TestClient(app).get("/api/v1/agents")
    assert response.status_code == 403
    assert response.json()["error"]["correlation_id"]


@pytest.mark.parametrize("days", [0, 91, "oops"])
def test_window_is_bounded(days):
    app.dependency_overrides[require_user] = user
    assert TestClient(app).get(f"/api/v1/agents?days={days}").status_code == 422


def test_agent_database_error_does_not_expose_details(monkeypatch):
    def unavailable(*args):
        raise psycopg.OperationalError("private connection details")

    monkeypatch.setattr(AgentTransparencyService, "summary", unavailable)
    app.dependency_overrides[require_user] = user
    response = TestClient(app).get("/api/v1/agents")
    assert response.status_code == 503
    assert "private" not in response.text
    assert response.json()["error"]["correlation_id"]


def test_service_window_and_role_cannot_be_bypassed():
    service = AgentTransparencyService("not-a-connection")
    with pytest.raises(AgentAccessDenied):
        service.summary(user("seller"))
    with pytest.raises(ValueError):
        service.summary(user(), 91)
