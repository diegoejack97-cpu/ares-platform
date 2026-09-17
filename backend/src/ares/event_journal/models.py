from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class IncomingCRMEvent(BaseModel):
    provider_event_id: str = Field(min_length=1, max_length=200)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.]+$")
    aggregate_type: Literal["lead", "contact", "company", "deal", "activity", "task"]
    aggregate_id: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class JournalEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    provider_event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: UUID = Field(default_factory=uuid4)
    source: Literal["crm"] = "crm"
    producer: str = Field(default="fake-crm", min_length=1, max_length=200)
    status: Literal["recorded"] = "recorded"
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any]


class JournalPage(BaseModel):
    items: list[JournalEvent]
    total: int
    source: str = "FakeCRM local"
    freshness_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AcceptedEvent(BaseModel):
    accepted: bool = True
    duplicate: bool
    event_id: UUID
    correlation_id: UUID
