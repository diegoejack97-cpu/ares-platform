from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser
from ares.chat.service import ChatFailure, ChatService


@pytest.fixture(autouse=True)
def clear_auth():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_chat_auth_and_validation():
    client = TestClient(app)
    assert client.get(f"/api/v1/chat/messages?scope_ref={uuid4()}").status_code == 401
    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(
        user_id=uuid4(), tenant_id=uuid4(), role="seller"
    )
    assert client.get(f"/api/v1/chat/messages?scope_ref={uuid4()}").status_code == 404
    for text in ["   ", "x" * 1201]:
        assert (
            client.post(
                "/api/v1/chat/messages", json={"text": text, "scope_ref": str(uuid4())}
            ).status_code
            == 422
        )


def test_preflight_failure_is_safe(monkeypatch):
    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(
        user_id=uuid4(), tenant_id=uuid4(), role="manager"
    )

    def fail(*args):
        raise ChatFailure("ai_budget_exceeded", 429)

    monkeypatch.setattr(ChatService, "prepare", fail)
    result = TestClient(app).post(
        "/api/v1/chat/messages", json={"text": "Resumo", "scope_ref": str(uuid4())}
    )
    assert result.status_code == 429
    assert result.json()["error"]["correlation_id"]
