"""Authenticated commercial queries, retaining every global request guard."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.intelligence.context_builder import ContextBuilder, ContextUnavailable
from ares.intelligence.queries import QueryIntent


def context_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/context", tags=["Trusted context"])
    dependency = Depends(require_user)
    builder = ContextBuilder(settings.database_url)

    def respond(operation: Callable[[], dict[str, Any]]) -> JSONResponse:
        try:
            return JSONResponse(
                content=jsonable_encoder(operation()), headers={"Cache-Control": "no-store"}
            )
        except (ContextUnavailable, psycopg.Error) as error:
            return JSONResponse(
                status_code=error.status if isinstance(error, ContextUnavailable) else 503,
                content={
                    "error": {
                        "code": error.code
                        if isinstance(error, ContextUnavailable)
                        else "context_service_unavailable",
                        "correlation_id": str(uuid4()),
                    }
                },
                headers={"Cache-Control": "no-store"},
            )

    @router.post("/query")
    def query(intent: QueryIntent, user: AuthenticatedUser = dependency) -> JSONResponse:
        return respond(lambda: builder.build(user, intent))

    @router.get("/{context_ref}")
    def get(context_ref: UUID, user: AuthenticatedUser = dependency) -> JSONResponse:
        return respond(lambda: builder.read(user, context_ref))

    return router
