from collections.abc import Callable
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ares.auth.models import AuthenticatedUser
from ares.command_center.models import CommandCenterSummary
from ares.command_center.service import CommandCenterDenied, CommandCenterService
from ares.config import Settings
from ares.impact.service import ImpactService


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "correlation_id": str(uuid4())}},
    )


def command_center_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["command-center"])
    service = CommandCenterService(
        settings.database_url, ImpactService(settings.database_url), settings.environment
    )
    dependency = Depends(require_user)

    @router.get("/command-center", response_model=CommandCenterSummary)
    def command_center(
        days: int = Query(30, ge=1, le=365), user: AuthenticatedUser = dependency
    ) -> Any:
        try:
            return service.summary(user, days)
        except CommandCenterDenied:
            return _error(403, "access_denied", "Acesso indisponível.")
        except ValueError:
            return _error(422, "invalid_window", "Período inválido.")
        except psycopg.Error:
            # Never echo driver details to the browser.
            return _error(
                503,
                "command_center_unavailable",
                "Não foi possível consultar o Command Center. Tente novamente.",
            )

    return router
