from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CanonicalEvent(BaseModel):
    id: UUID
    tenant_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: UUID
    occurred_at: datetime
    recorded_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class SignalDraft(BaseModel):
    signal_type: str
    rule_id: str
    rule_version: str
    severity: int = Field(ge=1, le=5)
    evidence: dict[str, Any]


class ScoreResult(BaseModel):
    score_version: str
    total_score: float = Field(ge=0, le=1)
    priority: int = Field(ge=0, le=3)
    breakdown: dict[str, Any]


class PipelineResult(BaseModel):
    event_id: UUID
    signal_ids: list[UUID]
    opportunity_id: UUID | None = None
    context_ref: UUID | None = None
    duplicate: bool = False
