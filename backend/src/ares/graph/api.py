from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.graph.models import OpportunityGraph
from ares.graph.service import GraphService, GraphUnavailable


def graph_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["M5 graph"])
    dependency = Depends(require_user)

    @router.get("/opportunities/{opportunity_id}/graph", response_model=OpportunityGraph)
    def read(
        opportunity_id: UUID,
        depth: int = Query(default=2, ge=1, le=2),
        user: AuthenticatedUser = dependency,
    ) -> Any:
        try:
            return GraphService(settings.database_url).read(user, opportunity_id, depth)
        except GraphUnavailable:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "graph_unavailable",
                        "message": "Grafo indisponível neste acesso.",
                        "correlation_id": str(uuid4()),
                    }
                },
            )
        except psycopg.Error:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "graph_read_failed",
                        "message": "Não foi possível consultar o grafo.",
                        "correlation_id": str(uuid4()),
                    }
                },
            )

    return router
