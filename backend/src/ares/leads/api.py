from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.integrations.service import IntegrationError
from ares.leads.models import LeadCandidate, LeadInput, LeadPage, LeadRecord, LeadResolve
from ares.leads.service import LeadService


def lead_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/leads", tags=["M6 leads"])
    dependency = Depends(require_user)

    def run(user: AuthenticatedUser, operation: Callable[[LeadService], Any]) -> Any:
        if settings.environment != "development" or user.tenant_id != settings.tenant_id:
            raise HTTPException(503, detail={"code": "client_crm_adapter_not_configured"})
        provider = FakeCRMHTTPProvider(
            settings.fake_crm_base_url,
            settings.fake_crm_api_key.get_secret_value(),
            settings.fake_crm_timeout_seconds,
        )
        try:
            return operation(LeadService(settings.database_url, provider))
        except IntegrationError as error:
            raise HTTPException(
                error.status, detail={"code": error.code, "correlation_id": error.correlation_id}
            ) from None
        except CRMProviderRequestError:
            raise HTTPException(503, detail={"code": "crm_unavailable"}) from None
        finally:
            provider.close()

    @router.get("", response_model=LeadPage)
    def listing(cursor: UUID | None = None, user: AuthenticatedUser = dependency) -> Any:
        return run(user, lambda service: service.listing(user, cursor))

    @router.post("", response_model=LeadRecord, status_code=201)
    def intake(command: LeadInput, user: AuthenticatedUser = dependency) -> Any:
        return run(user, lambda service: service.intake(user, command))

    @router.get("/{id}/candidates", response_model=list[LeadCandidate])
    def candidates(id: UUID, user: AuthenticatedUser = dependency) -> Any:
        return run(user, lambda service: service.candidates(user, id))

    @router.post("/{id}/resolve", response_model=LeadRecord)
    def resolve(id: UUID, command: LeadResolve, user: AuthenticatedUser = dependency) -> Any:
        return run(user, lambda service: service.resolve(user, id, command))

    return router
