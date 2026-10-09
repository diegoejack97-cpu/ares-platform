"""Versioned mapping and explicit human command contracts for M4."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

STAGES = {
    "new": "Entrada",
    "qualification": "Qualificação",
    "proposal": "Proposta",
    "negotiation": "Negociação",
    "won": "Ganho",
    "lost": "Perdido",
}
FIELDS = {"id", "title", "stage", "value", "currency", "version", "changed_at", "owner_id"}
REQUIRED = {"id", "title", "stage", "version", "changed_at"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class FieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_field: str
    provider_path: str = Field(min_length=1, max_length=80)
    transformation: Literal["identity", "uppercase"] = "identity"
    required: bool = False


class StageMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_stage: str = Field(min_length=1, max_length=80)
    canonical_stage: Literal["new", "qualification", "proposal", "negotiation", "won", "lost"]
    label: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=0, le=100)


class MappingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    fields: list[FieldMapping] = Field(min_length=5, max_length=8)
    stages: list[StageMapping] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_mapping(self) -> "MappingCommand":
        names = [field.canonical_field for field in self.fields]
        if len(set(names)) != len(names) or not REQUIRED <= set(names) <= FIELDS:
            raise ValueError("invalid_canonical_fields")
        for field in self.fields:
            if field.canonical_field in REQUIRED and not field.required:
                raise ValueError("required_field_cannot_be_optional")
            if field.canonical_field in {"id", "version", "changed_at"} and (
                field.provider_path != field.canonical_field or field.transformation != "identity"
            ):
                raise ValueError("source_identity_and_version_are_immutable")
        for name in ("external_stage", "canonical_stage", "position"):
            if len({getattr(stage, name) for stage in self.stages}) != len(self.stages):
                raise ValueError("ambiguous_stage_mapping")
        return self


class SyncCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["incremental", "reconcile", "historical"] = "incremental"
    since: datetime | None = None
    until: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "SyncCommand":
        if self.mode == "historical":
            if self.since is None or self.until is None:
                raise ValueError("historical_window_required")
            if self.since.tzinfo is None or self.until.tzinfo is None:
                raise ValueError("timezone_required")
            if not timedelta(0) < self.until - self.since <= timedelta(days=186):
                raise ValueError("historical_window_maximum_186_days")
            if self.until > datetime.now(UTC) + timedelta(minutes=1):
                raise ValueError("historical_window_in_future")
        elif self.since is not None or self.until is not None:
            raise ValueError("window_only_for_historical")
        return self


class StageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["new", "qualification", "proposal", "negotiation", "won", "lost"]
    expected_version: int = Field(ge=1)
    idempotency_key: UUID
    confirmed: bool
    reason: str | None = Field(default=None, max_length=500)


def suggested_mapping() -> dict[str, Any]:
    return {
        "fields": [
            {
                "canonical_field": name,
                "provider_path": name,
                "transformation": "identity",
                "required": name in REQUIRED,
            }
            for name in sorted(FIELDS)
        ],
        "stages": [
            {"external_stage": key, "canonical_stage": key, "label": label, "position": position}
            for position, (key, label) in enumerate(STAGES.items())
        ],
    }


def normalize(raw: dict[str, Any], mapping: MappingCommand) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in mapping.fields:
        value = raw.get(field.provider_path)
        if field.required and (value is None or value == ""):
            raise ValueError("required_source_field_missing")
        if field.transformation == "uppercase" and value is not None:
            if not isinstance(value, str):
                raise ValueError("uppercase_requires_text")
            value = value.upper()
        result[field.canonical_field] = value
    stages = {stage.external_stage: stage.canonical_stage for stage in mapping.stages}
    if result["stage"] not in stages:
        raise ValueError("unmapped_source_stage")
    result["canonical_stage"] = stages[result["stage"]]
    if not isinstance(result["id"], str) or not isinstance(result["title"], str):
        raise ValueError("source_identity_and_title_require_text")
    if type(result["version"]) is not int or result["version"] < 1:
        raise ValueError("invalid_source_version")
    changed = datetime.fromisoformat(str(result["changed_at"]))
    if changed.tzinfo is None:
        raise ValueError("source_timezone_required")
    result["changed_at"] = changed
    value = result.get("value")
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value < float("inf")
    ):
        raise ValueError("invalid_source_value")
    currency = result.get("currency")
    if currency is not None and (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise ValueError("invalid_source_currency")
    result["synthetic"] = bool(raw.get("synthetic", False))
    return result
