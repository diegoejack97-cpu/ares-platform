import base64

from fastapi.testclient import TestClient

from ares.connectors.fake_crm import FakeCRMProvider
from ares.fake_crm_sandbox.app import app

client = TestClient(app)
AUTH = {"Authorization": "Bearer local-sandbox-key"}


def setup_function() -> None:
    response = client.post("/v1/admin/reset", headers=AUTH)
    assert response.status_code == 200


def test_sandbox_exposes_deterministic_synthetic_dataset() -> None:
    assert client.get("/health").json()["synthetic"] is True
    assert client.get("/v1/deals").status_code == 401

    capabilities = client.get("/v1/capabilities", headers=AUTH).json()
    first = client.get("/v1/deals", params={"limit": 7}, headers=AUTH).json()
    second = client.get(
        "/v1/deals",
        params={"limit": 7, "cursor": first["next_cursor"]},
        headers=AUTH,
    ).json()
    state = client.get("/v1/admin/state", headers=AUTH).json()

    assert capabilities["read_changes"] is True
    assert capabilities["signed_webhooks"] is True
    assert state["counts"] == {
        "companies": 20,
        "contacts": 40,
        "deals": 60,
        "activities": 60,
        "tasks": 0,
        "notes": 0,
    }
    assert len(first["items"]) == 7
    assert set(item["id"] for item in first["items"]).isdisjoint(
        item["id"] for item in second["items"]
    )
    assert all(item["synthetic"] is True for item in first["items"])
    assert first["watermark"] is not None


def test_writes_are_idempotent_and_reject_key_reuse() -> None:
    headers = {**AUTH, "Idempotency-Key": "intent-task-001"}
    first = client.post(
        "/v1/deals/deal-001/tasks",
        json={"title": "Retomar proposta"},
        headers=headers,
    )
    duplicate = client.post(
        "/v1/deals/deal-001/tasks",
        json={"title": "Retomar proposta"},
        headers=headers,
    )
    conflict = client.post(
        "/v1/deals/deal-001/tasks",
        json={"title": "Conteúdo diferente"},
        headers=headers,
    )

    assert first.status_code == 200
    assert duplicate.json() == {"external_id": first.json()["external_id"], "duplicate": True}
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_key_reused_with_different_payload"


def test_stage_update_enforces_optimistic_version() -> None:
    stale = client.patch(
        "/v1/deals/deal-002/stage",
        json={"stage": "proposal", "expected_version": 99},
        headers={**AUTH, "Idempotency-Key": "intent-stage-stale"},
    )
    changed = client.patch(
        "/v1/deals/deal-002/stage",
        json={"stage": "proposal", "expected_version": 1},
        headers={**AUTH, "Idempotency-Key": "intent-stage-001"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "version_conflict"
    assert changed.status_code == 200


def test_sandbox_produces_a_webhook_accepted_by_ares_contract() -> None:
    response = client.post(
        "/v1/admin/events",
        json={"deal_id": "deal-003", "event_type": "deal.updated"},
        headers=AUTH,
    )
    fixture = response.json()
    raw_body = base64.b64decode(fixture["raw_body_base64"])
    event = FakeCRMProvider("local-dev-only-change-me").verify_and_normalize(
        raw_body,
        fixture["signature"],
    )

    assert response.status_code == 200
    assert event.aggregate_id == "deal-003"
    assert event.data["synthetic"] is True


def test_fault_profiles_are_explicit() -> None:
    response = client.get(
        "/v1/deals",
        headers={**AUTH, "X-FakeCRM-Scenario": "rate_limit"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.headers["X-Provider-Request-Id"]
    assert response.json()["detail"]["code"] == "simulated_rate_limit"
