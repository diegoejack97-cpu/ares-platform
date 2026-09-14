from collections.abc import Callable
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ares.agents.models import AgentSummary
from ares.agents.service import AgentAccessDenied, AgentTransparencyService
from ares.auth.models import AuthenticatedUser
from ares.config import Settings


def agent_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["M5 agents"])
    dependency = Depends(require_user)

    @router.get("/agents", response_model=AgentSummary)
    def agents(
        days: int = Query(default=30, ge=1, le=90),
        user: AuthenticatedUser = dependency,
    ) -> Any:
        try:
            return AgentTransparencyService(settings.database_url).summary(user, days)
        except AgentAccessDenied:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "access_denied",
                        "message": "Acesso indisponível.",
                        "correlation_id": str(uuid4()),
                    }
                },
            )
        except psycopg.Error:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "agent_metrics_unavailable",
                        "message": "Não foi possível consultar as execuções. Tente novamente.",
                        "correlation_id": str(uuid4()),
                    }
                },
            )

    return router
