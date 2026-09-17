from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.provider.models import CreateTenant, SetEntitlement


def test_provider_commands_require_reason_and_version():
    with pytest.raises(ValidationError):
        CreateTenant(name="Cliente", slug="cliente", reason=" ")
    with pytest.raises(ValidationError):
        SetEntitlement(module="ares_connect", status="active", reason="Contrato")
    with pytest.raises(ValidationError):
        SetEntitlement(module="unknown", status="active", expected_version=1, reason="Contrato")
    assert CreateTenant(name=" Cliente ", slug="cliente", reason=" Contrato ").name == "Cliente"


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
    finally:
        app.dependency_overrides.clear()
