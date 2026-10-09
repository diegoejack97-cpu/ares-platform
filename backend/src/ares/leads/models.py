import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_name(value: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        ).split()
    )


class LeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    idempotency_key: UUID

    @field_validator("email")
    @classmethod
    def email_value(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("invalid_email")
        return value.casefold()

    @field_validator("phone")
    @classmethod
    def phone_value(cls, value: str | None) -> str | None:
        if not value:
            return None
        number = re.sub(r"[^0-9]", "", value)
        if not 8 <= len(number) <= 15:
            raise ValueError("invalid_phone")
        return number

    @model_validator(mode="after")
    def identity(self) -> "LeadInput":
        if not self.email and not self.phone:
            raise ValueError("email_or_phone_required")
        return self

    def identity_hash(self) -> str:
        return hashlib.sha256(
            json.dumps([normalize_name(self.name), self.email, self.phone]).encode()
        ).hexdigest()


class LeadResolve(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["create", "merge", "discard", "undo"]
    expected_version: int = Field(ge=1)
    target_subject_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def target_for_merge_only(self) -> "LeadResolve":
        if (self.action == "merge") != (self.target_subject_id is not None):
            raise ValueError("target_required_only_for_merge")
        return self


class LeadRecord(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    status: str
    version: int
    owner_id: UUID
    target_subject_id: UUID | None
    external_id: str | None
    correlation_id: UUID
    created_at: datetime


class LeadPage(BaseModel):
    items: list[LeadRecord]
    next_cursor: UUID | None
    can_create: bool


class LeadCandidate(BaseModel):
    id: UUID
    display_name: str
    score: float
    reasons: list[str]
