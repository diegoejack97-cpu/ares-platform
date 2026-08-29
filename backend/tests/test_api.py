import asyncio

from fastapi.testclient import TestClient

from ares.api.app import app, journal


def test_fake_crm_event_crosses_webhook_journal_and_read_api() -> None:
    client = TestClient(app)

    accepted = client.post("/api/v1/dev/fake-crm/events", json={})
    response = client.get("/api/v1/journal/events")

    assert accepted.status_code == 202
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["producer"] == "fake-crm"


def teardown_function() -> None:
    asyncio.run(journal.clear())
