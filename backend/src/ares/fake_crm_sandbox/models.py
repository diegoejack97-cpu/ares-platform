from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SandboxDeal(BaseModel):
    id: str
    title: str
    stage: str
    value: float = Field(ge=0)
    currency: str = "BRL"
    version: int = Field(default=1, ge=1)
    changed_at: datetime
    owner_id: str | None
    company_id: str
    contact_id: str
    synthetic: Literal[True] = True
    scenario: str


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)


class CreateLeadRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)


class AddNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class UpdateStageRequest(BaseModel):
    stage: str = Field(min_length=1, max_length=80)
    expected_version: int | None = Field(default=None, ge=1)


class SandboxWriteResult(BaseModel):
    external_id: str
    duplicate: bool = False


class WebhookFixtureRequest(BaseModel):
    deal_id: str
    event_type: str = "deal.updated"
    data: dict[str, Any] = Field(default_factory=dict)
