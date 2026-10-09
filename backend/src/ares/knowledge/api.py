from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.impact.evaluation import Feedback, OutcomeService
from ares.intelligence.context_builder import ContextBuilder, ContextUnavailable
from ares.knowledge.models import DocumentUpload, MemoryConfig, MemoryQuery, Reason
from ares.knowledge.service import KnowledgeService


def knowledge_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/intelligence", tags=["Commercial memory and outcomes"])
    dependency = Depends(require_user)
    memory = KnowledgeService(settings.database_url)
    outcomes = OutcomeService(settings.database_url)

    def respond(operation: Callable[[], dict[str, Any]], status: int = 200) -> JSONResponse:
        try:
            return JSONResponse(
                status_code=status,
                content=jsonable_encoder(operation()),
                headers={"Cache-Control": "no-store"},
            )
        except (ContextUnavailable, psycopg.Error) as error:
            return JSONResponse(
                status_code=getattr(error, "status", 503),
                content={
                    "error": {
                        "code": getattr(error, "code", "intelligence_unavailable"),
                        "correlation_id": str(uuid4()),
                    }
                },
                headers={"Cache-Control": "no-store"},
            )

    @router.get("/memory/configuration")
    def configuration(user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: memory.configuration(user))

    @router.put("/memory/configuration")
    def configure(command: MemoryConfig, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: memory.configure(user, command))

    @router.get("/memory/documents")
    def documents(user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: memory.documents(user))

    @router.post("/memory/documents")
    def upload(command: DocumentUpload, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: memory.upload(user, command), 202)

    @router.post("/memory/documents/{document}/delete")
    def remove(document: UUID, command: Reason, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: memory.remove(user, document, command.reason))

    @router.post("/memory/query")
    def query(command: MemoryQuery, user: AuthenticatedUser = dependency) -> Any:
        return respond(
            lambda: ContextBuilder(settings.database_url).memory(
                user,
                command.question,
                command.purpose,
                key=settings.openai_api_key.get_secret_value(),
            )
        )

    @router.get("/outcomes/metrics")
    def metrics(days: int = 30, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: outcomes.metrics(user, days))

    @router.get("/outcomes/opportunity/{opportunity}")
    def opportunity(opportunity: UUID, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: outcomes.opportunity(user, opportunity))

    @router.get("/outcomes/{intervention}")
    def latest(intervention: UUID, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: outcomes.latest(user, intervention))

    @router.post("/outcomes/{intervention}")
    def start(intervention: UUID, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: outcomes.start(user, intervention), 202)

    @router.post("/outcomes/evaluation/{evaluation}/feedback")
    def feedback(evaluation: UUID, command: Feedback, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: outcomes.feedback(user, evaluation, command))

    @router.post("/outcomes/evaluation/{evaluation}/memory")
    def episode(evaluation: UUID, command: Reason, user: AuthenticatedUser = dependency) -> Any:
        return respond(lambda: outcomes.publish_episode(user, evaluation, command.reason), 202)

    return router
