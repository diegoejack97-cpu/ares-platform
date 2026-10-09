"""Authenticated control plane for opt-in analysis, never a CRM write endpoint."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ares.agents.contracts import RoutineCommand, StartAnalysis
from ares.agents.runtime import AgentRuntime, AgentRuntimeError
from ares.auth.models import AuthenticatedUser
from ares.config import Settings


def agent_runtime_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/agents", tags=["Agent execution"])
    dependency = Depends(require_user)
    runtime = AgentRuntime(
        settings.database_url,
        model_id=settings.openai_model,
        max_concurrent=settings.agent_max_concurrent_per_tenant,
    )

    def respond(operation: Callable[[], dict[str, Any]], status: int = 200) -> Any:
        try:
            result = operation()
            return JSONResponse(
                status_code=status,
                content=jsonable_encoder(result),
                headers={"Cache-Control": "no-store"},
            )
        except (AgentRuntimeError, psycopg.Error) as error:
            code = (
                error.code if isinstance(error, AgentRuntimeError) else "agent_service_unavailable"
            )
            return JSONResponse(
                status_code=error.status if isinstance(error, AgentRuntimeError) else 503,
                content={
                    "error": {
                        "code": code,
                        "message": "Não foi possível concluir a operação do agente.",
                        "correlation_id": str(uuid4()),
                    }
                },
                headers={"Cache-Control": "no-store"},
            )

    @router.get("/catalog")
    def catalog(user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.routines(user))

    @router.put("/routines/context-analysis")
    def configure(command: RoutineCommand, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.configure(user, command))

    @router.put("/routines/context-analysis/specialists")
    def specialists(command: RoutineCommand, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.configure_specialists(user, command))

    @router.get("/opportunities/{opportunity_id}/analysis")
    def analysis(opportunity_id: UUID, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.analysis(user, opportunity_id))

    @router.post("/workflows", status_code=202)
    def start(command: StartAnalysis, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.start(user, command), 202)

    @router.get("/workflows/{workflow_id}")
    def get(workflow_id: UUID, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.get(user, workflow_id))

    @router.post("/workflows/{workflow_id}/cancel")
    def cancel(workflow_id: UUID, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: runtime.cancel(user, workflow_id))

    return router
