"""Closed provider schema; the domain contract is validated again after conversion."""

from pydantic import BaseModel, ConfigDict

from ares.decision.models import ActionKind, TriageOutput


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None
    body: str | None
    stage: str | None
    due_in_hours: int | None


class ModelAction(BaseModel):
    action_kind: ActionKind
    payload: ActionPayload


class ModelAlternative(BaseModel):
    label: str
    action: ModelAction
    tradeoff: str


class ModelRecommendationOutput(BaseModel):
    recommended_action: ModelAction
    rationale: str
    confidence: float
    alternatives: list[ModelAlternative]
    contraindication: str | None
    triage: TriageOutput
