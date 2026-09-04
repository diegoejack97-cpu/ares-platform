from typing import Any

from fastapi.testclient import TestClient

from ares.api.app import app, get_fake_crm_lab, require_user
from ares.auth.models import AuthenticatedUser


class StubLabClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def snapshot(self) -> dict[str, Any]:
        return {
            "health": {"status": "ok", "service": "fake-crm-sandbox", "synthetic": True},
            "capabilities": {"read_deals": True},
            "stages": [{"id": "proposal", "label": "Proposal"}],
            "deals": [{"id": "deal-001", "title": "Synthetic Deal"}],
            "counts": {"deals": 60},
            "watermark": "2026-09-01T12:00:00Z",
            "freshness_at": "2026-09-03T12:00:00Z",
            "source": "FakeCRM HTTP Sandbox",
        }

    async def reset(self) -> dict[str, Any]:
        self.calls.append(("reset",))
        return {"reset": True}

    async def create_task(self, deal_id: str, title: str, key: str) -> dict[str, Any]:
        self.calls.append(("task", deal_id, title, key))
        return {"external_id": "task-0001", "duplicate": False}

    async def add_note(self, deal_id: str, body: str, key: str) -> dict[str, Any]:
        self.calls.append(("note", deal_id, body, key))
        return {"external_id": "note-0001", "duplicate": False}

    async def update_stage(
        self,
        deal_id: str,
        stage: str,
        version: int,
        key: str,
    ) -> dict[str, Any]:
        self.calls.append(("stage", deal_id, stage, str(version), key))
        return {"external_id": "stage-deal-001-v2", "duplicate": False}

    async def simulate_fault(self, scenario: str) -> dict[str, Any]:
        self.calls.append(("fault", scenario))
        return {
            "scenario": scenario,
            "observed": True,
            "status_code": 429,
            "code": "simulated_rate_limit",
            "retry_after": "1",
        }


def authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser.model_validate(
        {
            "user_id": "10000000-0000-0000-0000-000000000001",
            "tenant_id": "20000000-0000-0000-0000-000000000001",
            "email": "admin@ares.local",
            "role": "admin",
        }
    )


def test_lab_snapshot_requires_auth_and_hides_sandbox_key() -> None:
    stub = StubLabClient()
    app.dependency_overrides[require_user] = authenticated_user
    app.dependency_overrides[get_fake_crm_lab] = lambda: stub
    client = TestClient(app)

    response = client.get("/api/v1/dev/fake-crm/lab")

    assert response.status_code == 200
    assert response.json()["counts"]["deals"] == 60
    assert "api_key" not in response.text


def test_lab_forwards_idempotency_and_fault_scenario() -> None:
    stub = StubLabClient()
    app.dependency_overrides[require_user] = authenticated_user
    app.dependency_overrides[get_fake_crm_lab] = lambda: stub
    client = TestClient(app)

    task = client.post(
        "/api/v1/dev/fake-crm/lab/deals/deal-001/tasks",
        json={"title": "Retomar proposta"},
        headers={"Idempotency-Key": "intent-lab-001"},
    )
    fault = client.post("/api/v1/dev/fake-crm/lab/faults/rate_limit")

    assert task.status_code == 200
    assert fault.status_code == 200
    assert ("task", "deal-001", "Retomar proposta", "intent-lab-001") in stub.calls
    assert ("fault", "rate_limit") in stub.calls


def test_lab_rejects_anonymous_access() -> None:
    app.dependency_overrides.clear()
    client = TestClient(app)
    assert client.get("/api/v1/dev/fake-crm/lab").status_code == 401


def test_lab_rejects_non_admin_user() -> None:
    user = authenticated_user().model_copy(update={"role": "seller"})
    app.dependency_overrides[require_user] = lambda: user
    client = TestClient(app)
    assert client.get("/api/v1/dev/fake-crm/lab").status_code == 403


def teardown_function() -> None:
    app.dependency_overrides.clear()
