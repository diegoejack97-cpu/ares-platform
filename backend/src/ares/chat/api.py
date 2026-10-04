from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ares.auth.models import AuthenticatedUser
from ares.chat.service import ChatFailure, ChatService
from ares.config import Settings


class ChatCommand(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    scope_ref: UUID | None = None

    @field_validator("text")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_message")
        return value.strip()


class ChatCitation(BaseModel):
    event_id: str
    event_type: str | None = None
    occurred_at: str | None = None
    source: str | None = None
    source_ref: str | None = None
    opportunity_id: UUID | None = None


class ChatContext(BaseModel):
    context_ref: str
    content: str
    content_hash: str
    tokens_upper_bound: int
    token_limit: int
    count_method: str
    citations: list[ChatCitation]
    truncated: bool
    captured_at: datetime
    source: str
    instruction_tokens_upper_bound: int | None = None
    question_tokens_upper_bound: int | None = None


class ChatTool(BaseModel):
    name: str
    status: str


class ChatExchange(BaseModel):
    id: UUID
    user_text: str
    assistant_text: str
    status: str
    context_json: ChatContext
    tool_calls_json: list[ChatTool]
    created_at: datetime


class ChatHistory(BaseModel):
    items: list[ChatExchange]
    context: ChatContext
    model_available: bool


def chat_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/chat", tags=["M5 chat"])
    dependency = Depends(require_user)
    service = ChatService(settings)

    def error(failure: ChatFailure) -> JSONResponse:
        return JSONResponse(
            status_code=failure.status,
            content={
                "error": {
                    "code": failure.code,
                    "message": "Consulta de chat indisponível.",
                    "correlation_id": str(uuid4()),
                }
            },
        )

    @router.get("/messages", response_model=ChatHistory)
    def history(scope_ref: UUID | None = None, user: AuthenticatedUser = dependency) -> Any:
        try:
            return service.history(user, scope_ref)
        except ChatFailure as failure:
            return error(failure)
        except (psycopg.Error, RuntimeError, ValueError):
            return error(ChatFailure("chat_read_failed"))

    @router.post("/messages")
    def send(command: ChatCommand, user: AuthenticatedUser = dependency) -> Any:
        try:
            prepared = service.prepare(user, command.scope_ref, command.text)
        except ChatFailure as failure:
            return error(failure)
        except (psycopg.Error, RuntimeError, ValueError):
            return error(ChatFailure("chat_preflight_failed"))
        return StreamingResponse(
            service.stream(prepared),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
