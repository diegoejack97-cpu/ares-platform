from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.provider.models import (
    CreateTenant,
    SetEntitlement,
    SetInitialAdmin,
    SetPackage,
    SetTenantStatus,
)


def test_provider_commands_require_reason_and_version():
    with pytest.raises(ValidationError):
        CreateTenant(name="Cliente", slug="cliente", reason=" ")
    with pytest.raises(ValidationError):
        SetEntitlement(module="ares_connect", status="active", reason="Contrato")
    with pytest.raises(ValidationError):
        SetEntitlement(module="unknown", status="active", expected_version=1, reason="Contrato")
    assert CreateTenant(name=" Cliente ", slug="cliente", reason=" Contrato ").name == "Cliente"
    with pytest.raises(ValidationError):
        SetPackage(
            package="full_connect",
            expires_at="2020-01-01T00:00:00Z",
            expected_version=1,
            reason="Contrato",
        )
    status = SetTenantStatus(status="suspended", expected_version=1, reason="Pausa")
    assert status.status == "suspended"
    admin = SetInitialAdmin(email=" Gestor@Example.com ", expected_version=1, reason="Contrato")
    assert admin.email == "gestor@example.com"


def test_product_admin_does_not_imply_provider_access():
    from fastapi.testclient import TestClient

    from ares.api.app import app, require_user
    from ares.auth.models import AuthenticatedUser

    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(
        user_id=uuid4(), tenant_id=uuid4(), role="admin"
    )
    try:
        response = TestClient(app).get("/api/v1/admin/tenants")
        assert response.status_code == 401
        assert response.json()["error"]["correlation_id"]
        assert TestClient(app).get("/api/v1/admin/me").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_expired_connect_plan_blocks_product_api(monkeypatch):
    from fastapi.testclient import TestClient

    from ares.api.app import app, auth_service
    from ares.auth.models import AuthenticatedUser

    tenant_id = uuid4()

    async def authenticate(_token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=uuid4(), tenant_id=tenant_id, role="admin")

    monkeypatch.setattr(auth_service, "authenticate", authenticate)
    monkeypatch.setattr(auth_service, "has_connect_access", lambda _tenant: False)
    response = TestClient(app).get(
        "/api/v1/opportunities", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "ares_connect_plan_inactive"
