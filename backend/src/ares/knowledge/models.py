from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PURPOSES = ("chat", "diagnosis", "recommendation", "sentinel", "portfolio", "outcome")


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    enabled: bool = False
    external_consent: bool = False
    outcomes_enabled: bool = False
    episodes_enabled: bool = False
    observation_hours: int = Field(default=48, ge=1, le=720)
    retention_days: int = Field(default=90, ge=1, le=365)
    reason: str = Field(min_length=8, max_length=300)


class DocumentUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID | None = None
    expected_version: int = Field(default=0, ge=0)
    filename: str = Field(min_length=1, max_length=120, pattern=r"(?i)^[^/\\]+\.(txt|md)$")
    title: str = Field(min_length=3, max_length=160)
    source_label: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=10, max_length=262144)
    classification: Literal["internal", "restricted"] = "internal"
    allowed_roles: list[Literal["admin", "manager", "seller", "auditor"]] = Field(
        default=["admin", "manager"], min_length=1, max_length=4
    )
    owner_user_id: UUID | None = None
    purposes: list[
        Literal["chat", "diagnosis", "recommendation", "sentinel", "portfolio", "outcome"]
    ] = Field(default=["chat"], min_length=1, max_length=6)
    validity_days: int = Field(default=90, ge=1, le=365)
    verified_source: Literal[True]
    reason: str = Field(min_length=8, max_length=300)


class MemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1200)
    purpose: Literal["chat", "diagnosis", "recommendation", "sentinel", "portfolio", "outcome"] = (
        "chat"
    )


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=8, max_length=300)
