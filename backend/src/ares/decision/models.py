from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ActionKind = Literal["create_task", "add_note", "update_stage"]


class ActionDraft(BaseModel):
    action_kind: ActionKind
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload(self) -> "ActionDraft":
        required = {
            "create_task": "title",
            "add_note": "body",
            "update_stage": "stage",
        }[self.action_kind]
        value = self.payload.get(required)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"payload.{required} is required")
        self.payload.pop("target", None)
        self.payload.pop("deal_id", None)
        return self


class ActionAlternative(BaseModel):
    label: str = Field(min_length=3, max_length=120)
    action: ActionDraft
    tradeoff: str = Field(min_length=3, max_length=300)


class TriageOutput(BaseModel):
    urgency: Literal["low", "normal", "high", "critical"]
    reason: str = Field(min_length=3, max_length=400)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)


class RecommendationOutput(BaseModel):
    recommended_action: ActionDraft
    rationale: str = Field(min_length=8, max_length=800)
    confidence: float = Field(ge=0, le=1)
    alternatives: list[ActionAlternative] = Field(min_length=1, max_length=3)
    contraindication: str | None = Field(default=None, max_length=500)
    triage: TriageOutput


class DecideCommand(BaseModel):
    verdict: Literal["approved", "edited", "rejected"]
    expected_version: int = Field(gt=0)
    edited_payload: ActionDraft | None = None
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_edit(self) -> "DecideCommand":
        if self.verdict == "edited" and self.edited_payload is None:
            raise ValueError("edited_payload is required when verdict is edited")
        if self.verdict != "edited" and self.edited_payload is not None:
            raise ValueError("edited_payload is only accepted when verdict is edited")
        return self
