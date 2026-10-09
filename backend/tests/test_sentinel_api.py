"""The schedule API isolates tenant changes and reserves writes for administrators."""

from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser
from ares.sentinels.service import SentinelScheduleConflict, SentinelService


@pytest.fixture(autouse=True)
def clean_auth():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def user(role: str = "admin") -> AuthenticatedUser:
    return AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role=role)


def command() -> dict[str, object]:
    return {
        "expected_version": 1,
        "enabled": True,
        "interval_minutes": 60,
        "start_time_local": "08:30",
        "reason": "Ajustar janela comercial",
    }


def test_schedule_requires_auth_and_admin_for_writes(monkeypatch):
    assert TestClient(app).get("/api/v1/sentinels/config").status_code == 401
    app.dependency_overrides[require_user] = lambda: user("seller")

    def database_should_not_be_called(*args):
        raise AssertionError("unauthorized write reached the database")

    monkeypatch.setattr(SentinelService, "update_schedule_sync", database_should_not_be_called)
    response = TestClient(app).put("/api/v1/sentinels/config", json=command())
    assert response.status_code == 403


def test_schedule_validates_frequency_before_writing(monkeypatch):
    app.dependency_overrides[require_user] = lambda: user("admin")

    def database_should_not_be_called(*args):
        raise AssertionError("invalid command reached the database")

    monkeypatch.setattr(SentinelService, "update_schedule_sync", database_should_not_be_called)
    response = TestClient(app).put(
        "/api/v1/sentinels/config", json={**command(), "interval_minutes": 7}
    )
    assert response.status_code == 422


def test_admin_write_uses_authenticated_tenant_and_actor(monkeypatch):
    admin = user()
    app.dependency_overrides[require_user] = lambda: admin
    captured = []

    def update(self, tenant_id, actor_id, payload):
        captured.append((tenant_id, actor_id, payload))
        return {
            "rule_id": "SENTINEL-SLA-OVERDUE",
            "kind": "sla_overdue",
            "title": "SLA vencido",
            "definition": "Oportunidade ARES aberta com prazo de SLA vencido.",
            "threshold_hours": 0,
            "enabled": True,
            "interval_minutes": 60,
            "start_time_local": time(8, 30),
            "timezone": "America/Sao_Paulo",
            "next_run_at": datetime(2026, 9, 29, 12, tzinfo=UTC),
            "last_run_at": None,
            "last_created_count": None,
            "version": 2,
            "updated_at": datetime(2026, 9, 29, 11, tzinfo=UTC),
            "sentinel_slots": 1,
            "can_run": True,
        }

    monkeypatch.setattr(SentinelService, "update_schedule_sync", update)
    response = TestClient(app).put("/api/v1/sentinels/config", json=command())
    assert response.status_code == 200
    assert captured[0][:2] == (admin.tenant_id, admin.user_id)
    assert captured[0][2].reason == command()["reason"]
    assert response.json()["version"] == 2


def test_stale_schedule_returns_conflict(monkeypatch):
    app.dependency_overrides[require_user] = lambda: user("admin")

    def conflict(*args):
        raise SentinelScheduleConflict("stale_sentinel_schedule")

    monkeypatch.setattr(SentinelService, "update_schedule_sync", conflict)
    response = TestClient(app).put("/api/v1/sentinels/config", json=command())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_sentinel_schedule"


def test_rule_creation_rejects_freeform_condition_and_non_admin(monkeypatch):
    app.dependency_overrides[require_user] = lambda: user("seller")
    body = {
        "title": "Sem responsável",
        "kind": "unassigned",
        "threshold_hours": 24,
        "enabled": True,
        "interval_minutes": 120,
        "start_time_local": "09:00",
        "reason": "Acompanhar oportunidades sem dono",
    }

    def database_should_not_be_called(*args):
        raise AssertionError("unauthorized write reached the database")

    monkeypatch.setattr(SentinelService, "save_rule_sync", database_should_not_be_called)
    assert TestClient(app).post("/api/v1/sentinels/rules", json=body).status_code == 403
    app.dependency_overrides[require_user] = user
    assert (
        TestClient(app)
        .post("/api/v1/sentinels/rules", json={**body, "kind": "arbitrary_sql"})
        .status_code
        == 422
    )


def test_rule_creation_uses_authenticated_scope(monkeypatch):
    admin = user()
    app.dependency_overrides[require_user] = lambda: admin
    captured = []

    def create(self, tenant_id, actor_id, payload, rule_id=None):
        captured.append((tenant_id, actor_id, payload, rule_id))
        return {
            "rule_id": "SENTINEL-test",
            "kind": "unassigned",
            "title": payload.title,
            "definition": "Oportunidade ARES aberta sem responsável definido.",
            "threshold_hours": payload.threshold_hours,
            "enabled": payload.enabled,
            "interval_minutes": payload.interval_minutes,
            "start_time_local": payload.start_time_local,
            "timezone": "America/Sao_Paulo",
            "next_run_at": None,
            "last_run_at": None,
            "last_created_count": None,
            "version": 1,
            "updated_at": datetime(2026, 9, 29, 11, tzinfo=UTC),
            "sentinel_slots": 2,
            "can_run": False,
        }

    monkeypatch.setattr(SentinelService, "save_rule_sync", create)
    response = TestClient(app).post(
        "/api/v1/sentinels/rules",
        json={
            "title": "Sem responsável",
            "kind": "unassigned",
            "threshold_hours": 24,
            "enabled": False,
            "interval_minutes": 120,
            "start_time_local": "09:00",
            "reason": "Acompanhar oportunidades sem dono",
        },
    )
    assert response.status_code == 201
    assert captured[0][:2] == (admin.tenant_id, admin.user_id)
    assert captured[0][2].kind == "unassigned"
