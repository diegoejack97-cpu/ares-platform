from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ares.config import Settings
from ares.provider.auth import ProviderAuth
from ares.provider.billing import BillingCommand, set_billing
from ares.provider.models import (
    CreateTenant,
    ProviderPrincipal,
    SetEntitlement,
    SetInitialAdmin,
    SetPackage,
    SetTenantStatus,
    TenantConfiguration,
    TenantPage,
    TenantRecord,
)
from ares.provider.quotas import QuotaCommand, set_quota
from ares.provider.service import ProviderConflict, ProviderDenied, ProviderMissing, ProviderService


class ProviderHTTPError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def install_provider_api(app: FastAPI, settings: Settings) -> None:
    router = APIRouter(prefix="/api/v1/admin", tags=["M6 provider"])
    auth = ProviderAuth(settings)
    service = ProviderService(settings.database_url)
    security = HTTPBearer(auto_error=False, scheme_name="ProviderSession")
    security_dependency = Depends(security)

    async def error_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, ProviderHTTPError)
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": "Operação do provedor indisponível.",
                    "correlation_id": str(uuid4()),
                }
            },
        )

    app.add_exception_handler(ProviderHTTPError, error_handler)

    async def require_provider(
        credentials: HTTPAuthorizationCredentials | None = security_dependency,
    ) -> ProviderPrincipal:
        if credentials is None:
            raise ProviderHTTPError(401, "provider_session_required")
        try:
            return await auth.authenticate(credentials.credentials)
        except ProviderDenied:
            raise ProviderHTTPError(403, "provider_access_denied") from None
        except (psycopg.Error, httpx.HTTPError):
            raise ProviderHTTPError(503, "provider_auth_unavailable") from None

    dependency = Depends(require_provider)

    def execute(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except ProviderDenied:
            raise ProviderHTTPError(403, "provider_access_denied") from None
        except ProviderMissing:
            raise ProviderHTTPError(404, "tenant_unavailable") from None
        except ProviderConflict as failure:
            raise ProviderHTTPError(409, failure.code) from None
        except psycopg.errors.UniqueViolation:
            raise ProviderHTTPError(409, "configuration_conflict") from None
        except psycopg.Error:
            raise ProviderHTTPError(503, "provider_operation_failed") from None

    @router.get("/me")
    def current_provider(actor: ProviderPrincipal = dependency) -> dict[str, str]:
        return {"role": "provider", "user_id": str(actor.user_id)}

    @router.get("/tenants", response_model=TenantPage)
    def listing(
        cursor: UUID | None = None,
        limit: int = Query(25, ge=1, le=100),
        actor: ProviderPrincipal = dependency,
    ) -> Any:
        return execute(lambda: service.list_tenants(actor, cursor, limit))

    @router.get("/tenants/{tenant_id}", response_model=TenantConfiguration)
    def detail(tenant_id: UUID, actor: ProviderPrincipal = dependency) -> Any:
        return execute(lambda: service.detail(actor, tenant_id))

    @router.post("/tenants", response_model=TenantRecord, status_code=201)
    def create(command: CreateTenant, actor: ProviderPrincipal = dependency) -> Any:
        return execute(lambda: service.create(actor, command))

    @router.post("/tenants/{tenant_id}/status", response_model=TenantRecord)
    def tenant_status(
        tenant_id: UUID, command: SetTenantStatus, actor: ProviderPrincipal = dependency
    ) -> Any:
        return execute(lambda: service.set_status(actor, tenant_id, command))

    @router.post("/tenants/{tenant_id}/initial-admin", response_model=TenantRecord)
    def initial_admin(
        tenant_id: UUID, command: SetInitialAdmin, actor: ProviderPrincipal = dependency
    ) -> Any:
        return execute(lambda: service.assign_initial_admin(actor, tenant_id, command))

    @router.post("/tenants/{tenant_id}/package", response_model=TenantRecord)
    def package(tenant_id: UUID, command: SetPackage, actor: ProviderPrincipal = dependency) -> Any:
        return execute(lambda: service.assign_package(actor, tenant_id, command))

    @router.post("/tenants/{tenant_id}/entitlements", response_model=TenantRecord)
    def entitle(
        tenant_id: UUID, command: SetEntitlement, actor: ProviderPrincipal = dependency
    ) -> Any:
        return execute(lambda: service.entitle(actor, tenant_id, command))

    @router.post("/tenants/{tenant_id}/billing", response_model=TenantRecord)
    def billing(
        tenant_id: UUID, command: BillingCommand, actor: ProviderPrincipal = dependency
    ) -> Any:
        return execute(lambda: set_billing(service, actor, tenant_id, command))

    @router.post("/tenants/{tenant_id}/quotas", response_model=TenantRecord)
    def quota(tenant_id: UUID, command: QuotaCommand, actor: ProviderPrincipal = dependency) -> Any:
        return execute(lambda: set_quota(service, actor, tenant_id, command))

    app.include_router(router)
