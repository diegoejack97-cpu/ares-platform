from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ares.auth.models import AuthenticatedUser
from ares.chat.handoff import FindingChat
from ares.chat.service import ChatFailure, ChatService
from ares.config import Settings
from ares.sentinels.service import SentinelScheduleConflict


class ChatCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1200)
    scope_ref: UUID | None = None
    finding_ref: UUID | None = None

    @model_validator(mode="after")
    def single_scope(self) -> "ChatCommand":
        if self.scope_ref and self.finding_ref:
            raise ValueError("ambiguous_chat_scope")
        return self

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


class ChatFindingOrigin(BaseModel):
    finding_id: UUID
    opportunity_id: UUID
    revision: int
    title: str
    rule_title: str
    detected_at: datetime
    status: str
    condition_current: bool
    changed: bool
    summary: str
    source: str
    suggestions: list[str]


class ChatHistory(BaseModel):
    items: list[ChatExchange]
    context: ChatContext
    model_available: bool
    next_before: UUID | None = None
    finding: ChatFindingOrigin | None = None


class ChatFeedbackCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["helpful", "unhelpful"]
    reason: str = Field(default="", max_length=500)


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
    def history(
        scope_ref: UUID | None = None,
        finding_ref: UUID | None = None,
        before: UUID | None = None,
        user: AuthenticatedUser = dependency,
    ) -> Any:
        try:
            if scope_ref and finding_ref:
                raise ChatFailure("ambiguous_chat_scope", 422)
            return service.history(user, scope_ref, finding_ref, before)
        except ChatFailure as failure:
            return error(failure)
        except SentinelScheduleConflict:
            return error(ChatFailure("chat_access_unavailable", 403))
        except (psycopg.Error, RuntimeError, ValueError):
            return error(ChatFailure("chat_read_failed"))

    @router.post("/messages")
    def send(command: ChatCommand, user: AuthenticatedUser = dependency) -> Any:
        try:
            prepared = service.prepare(user, command.scope_ref, command.text, command.finding_ref)
        except ChatFailure as failure:
            return error(failure)
        except SentinelScheduleConflict:
            return error(ChatFailure("chat_access_unavailable", 403))
        except (psycopg.Error, RuntimeError, ValueError):
            return error(ChatFailure("chat_preflight_failed"))
        return StreamingResponse(
            service.stream(prepared),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.post("/findings/{finding_id}/open")
    def open_finding(finding_id: UUID, user: AuthenticatedUser = dependency) -> Any:
        try:
            return JSONResponse(
                content=jsonable_encoder(FindingChat(settings.database_url).open(user, finding_id)),
                headers={"Cache-Control": "no-store"},
            )
        except ChatFailure as failure:
            return error(failure)
        except SentinelScheduleConflict:
            return error(ChatFailure("chat_access_unavailable", 403))
        except (psycopg.Error, RuntimeError, ValueError):
            return error(ChatFailure("finding_handoff_failed"))

    @router.put("/messages/{message_id}/feedback")
    def feedback(
        message_id: UUID, command: ChatFeedbackCommand, user: AuthenticatedUser = dependency
    ) -> Any:
        try:
            return FindingChat(settings.database_url).feedback(
                user, message_id, command.rating, command.reason
            )
        except ChatFailure as failure:
            return error(failure)
        except SentinelScheduleConflict:
            return error(ChatFailure("chat_access_unavailable", 403))
        except (psycopg.Error, RuntimeError, ValueError):
            return error(ChatFailure("chat_feedback_failed"))

    return router
