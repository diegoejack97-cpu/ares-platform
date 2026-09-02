import asyncio
from uuid import UUID

from fastapi.testclient import TestClient

from ares.api.app import app, journal, require_user
from ares.auth.models import AuthenticatedUser


def authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UUID("10000000-0000-0000-0000-000000000001"),
        tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
        email="admin@ares.local",
        role="admin",
    )


def test_fake_crm_event_crosses_webhook_journal_and_read_api() -> None:
    app.dependency_overrides[require_user] = authenticated_user
    client = TestClient(app)

    accepted = client.post("/api/v1/dev/fake-crm/events", json={})
    response = client.get("/api/v1/journal/events")
    ready = client.get("/health/ready")

    assert accepted.status_code == 202
    assert response.status_code == 200
    assert ready.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["producer"] == "fake-crm"


def test_journal_rejects_anonymous_access() -> None:
    app.dependency_overrides.clear()
    client = TestClient(app)
    assert client.get("/api/v1/journal/events").status_code == 401


def teardown_function() -> None:
    app.dependency_overrides.clear()
    asyncio.run(journal.clear())
