"""Typed control plane for commercial agents; no caller-provided snapshots."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ares.agents.commercial_contracts import CommercialConfig, PortfolioRequest, PortfolioView
from ares.agents.commercial_service import CommercialService
from ares.agents.runtime import AgentRuntimeError
from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.decision.execution_guard import ExecutionBlocked
from ares.intelligence.context_builder import ContextUnavailable


def commercial_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/agents/commercial", tags=["Commercial agents"])
    service = CommercialService(settings.database_url, settings.openai_model)
    dependency = Depends(require_user)

    def respond(operation: Callable[[], dict[str, Any]], status: int = 200) -> JSONResponse:
        try:
            return JSONResponse(
                status_code=status,
                content=jsonable_encoder(operation()),
                headers={"Cache-Control": "no-store"},
            )
        except (AgentRuntimeError, ContextUnavailable, ExecutionBlocked, psycopg.Error) as error:
            return JSONResponse(
                status_code=getattr(
                    error, "status", 403 if isinstance(error, ExecutionBlocked) else 503
                ),
                content={
                    "error": {
                        "code": getattr(error, "code", "commercial_unavailable"),
                        "correlation_id": str(uuid4()),
                    }
                },
                headers={"Cache-Control": "no-store"},
            )

    @router.get("/configuration")
    def configuration(user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: service.configuration(user))

    @router.put("/configuration")
    def configure(command: CommercialConfig, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: service.configure(user, command))

    @router.get("/portfolio", response_model=PortfolioView)
    def latest(
        criterion: str = "urgency",
        currency: str | None = None,
        user: AuthenticatedUser = dependency,
    ) -> Any:
        from pydantic import ValidationError

        try:
            command = PortfolioRequest.model_validate(
                {"criterion": criterion, "currency": currency}
            )
        except ValidationError:
            return JSONResponse(
                status_code=422, content={"error": {"code": "portfolio_criterion_invalid"}}
            )
        return respond(
            lambda: PortfolioView.model_validate(service.latest(user, command)).model_dump(
                mode="json"
            )
        )

    @router.post("/portfolio", status_code=202)
    def start(command: PortfolioRequest, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: service.start(user, command), 202)

    return router
