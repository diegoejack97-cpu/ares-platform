from typing import Any
from uuid import UUID

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ares.auth.models import AuthenticatedUser
from ares.command_center import api as command_center_api
from ares.command_center.service import (
    FORBIDDEN_CLAIMS,
    MAIN_PATH_STATES,
    RENDERED_KEYS,
    CommandCenterDenied,
    CommandCenterService,
    definitions,
    pad_funnel,
)
from ares.config import Settings

USER = AuthenticatedUser(
    user_id=UUID("10000000-0000-0000-0000-000000000001"),
    tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
    role="admin",
)


def client(summary: Any) -> TestClient:
    settings = Settings(database_url="postgresql://unused", environment="development")
    app = FastAPI()

    def require_user() -> AuthenticatedUser:
        return USER

    class Stub(CommandCenterService):
        def summary(self, user: AuthenticatedUser, days: int = 30) -> dict[str, Any]:
            return summary(user, days)

    original = command_center_api.CommandCenterService
    command_center_api.CommandCenterService = Stub  # type: ignore[misc]
    try:
        app.include_router(command_center_api.command_center_router(settings, require_user))
    finally:
        command_center_api.CommandCenterService = original  # type: ignore[misc]
    return TestClient(app)


def test_days_bounds_are_rejected_before_the_service():
    calls: list[int] = []

    def summary(user: AuthenticatedUser, days: int) -> dict[str, Any]:
        calls.append(days)
        return {}

    api = client(summary)
    for value in ("0", "366", "abc"):
        assert api.get(f"/api/v1/command-center?days={value}").status_code == 422
    assert calls == []


def test_denied_uses_the_error_envelope():
    def summary(user: AuthenticatedUser, days: int) -> dict[str, Any]:
        raise CommandCenterDenied

    body = client(summary).get("/api/v1/command-center").json()
    assert body["error"]["code"] == "access_denied"
    UUID(body["error"]["correlation_id"])


def test_database_error_does_not_expose_details():
    def summary(user: AuthenticatedUser, days: int) -> dict[str, Any]:
        raise psycopg.OperationalError("private connection details")

    response = client(summary).get("/api/v1/command-center")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "command_center_unavailable"
    assert "private connection details" not in response.text


def test_service_rejects_window_before_connecting():
    service = CommandCenterService("postgresql://unused", None, "development")  # type: ignore[arg-type]
    for days in (0, 366):
        try:
            service.summary(USER, days)
        except ValueError as error:
            assert str(error) == "invalid_window"
        else:
            raise AssertionError("window accepted")


def test_definitions_cover_rendered_keys_without_causal_claims():
    items = definitions(30)
    assert {item["key"] for item in items} == RENDERED_KEYS
    assert len(items) == len(RENDERED_KEYS)
    for item in items:
        text = f"{item['formula']} {item['attribution']}".lower()
        for claim in FORBIDDEN_CLAIMS:
            assert claim not in text, (item["key"], claim)
        assert item["tables"] and item["period"]
    assert "Janela de 30 dias" in next(i for i in items if i["key"] == "funnel")["period"]


def test_pad_funnel_keeps_state_order_and_zero_fills():
    stages = pad_funnel({"authorized": 3, "closed": 1})
    assert [stage["state"] for stage in stages] == list(MAIN_PATH_STATES)
    assert [stage["reached"] for stage in stages] == [0, 0, 0, 3, 0, 0, 1]
    assert stages[2]["label"] == "Aguardando decisão"
