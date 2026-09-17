from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.integrations.models import MappingCommand, StageCommand, SyncCommand
from ares.integrations.pipeline import PipelineService
from ares.integrations.service import IntegrationError


def integration_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["M4 integrations"])
    user_dependency = Depends(require_user)

    def run(user: AuthenticatedUser, operation: Callable[[PipelineService], Any]) -> Any:
        # The only implemented adapter is the explicit local sandbox, never a pretend client CRM.
        if settings.environment != "development" or user.tenant_id != settings.tenant_id:
            raise HTTPException(503, detail={"code": "client_crm_adapter_not_configured"})
        provider = FakeCRMHTTPProvider(
            settings.fake_crm_base_url,
            settings.fake_crm_api_key.get_secret_value(),
            settings.fake_crm_timeout_seconds,
        )
        try:
            return operation(PipelineService(settings.database_url, user.tenant_id, provider))
        except IntegrationError as error:
            raise HTTPException(
                error.status, detail={"code": error.code, "correlation_id": error.correlation_id}
            ) from error
        except CRMProviderRequestError as error:
            raise HTTPException(503, detail={"code": error.code}) from error
        except ValueError as error:
            raise HTTPException(422, detail={"code": "invalid_source_mapping"}) from error
        finally:
            provider.close()

    @router.get("/integrations/mapping")
    def mapping(user: AuthenticatedUser = user_dependency) -> Any:
        return run(user, lambda service: service.get_mapping())

    @router.put("/integrations/mapping")
    def save_mapping(command: MappingCommand, user: AuthenticatedUser = user_dependency) -> Any:
        return run(user, lambda service: service.save_mapping(user, command))

    @router.post("/integrations/sync", status_code=202)
    def sync(command: SyncCommand, user: AuthenticatedUser = user_dependency) -> Any:
        return run(user, lambda service: service.enqueue(user, command))

    @router.get("/integrations/jobs")
    def jobs(user: AuthenticatedUser = user_dependency) -> Any:
        return run(user, lambda service: service.jobs())

    @router.post("/integrations/jobs/{job_id}/retry", status_code=202)
    def retry(job_id: UUID, user: AuthenticatedUser = user_dependency) -> Any:
        return run(user, lambda service: service.retry(user, job_id))

    @router.get("/pipeline")
    def pipeline(cursor: UUID | None = None, user: AuthenticatedUser = user_dependency) -> Any:
        return run(user, lambda service: service.pipeline(user, cursor))

    @router.post("/pipeline/deals/{deal_id}/stage")
    def move(
        deal_id: UUID, command: StageCommand, user: AuthenticatedUser = user_dependency
    ) -> Any:
        return run(user, lambda service: service.move(user, deal_id, command))

    return router
