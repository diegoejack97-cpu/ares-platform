"""Typed, tenant-scoped schedules for bounded sentinel rule templates."""

from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SentinelInterval = Literal[1, 5, 15, 30, 60, 120, 360, 720, 1440]
SentinelKind = Literal["sla_overdue", "unassigned", "stale"]


class SentinelScheduleCommand(BaseModel):
    expected_version: int = Field(ge=1)
    enabled: bool
    interval_minutes: SentinelInterval
    start_time_local: time
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("start_time_local")
    @classmethod
    def minute_precision(cls, value: time) -> time:
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("local_time_must_use_minute_precision")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("reason_required")
        return value


class SentinelSchedule(BaseModel):
    rule_id: str
    kind: SentinelKind
    title: str
    definition: str
    threshold_hours: int
    enabled: bool
    interval_minutes: SentinelInterval
    start_time_local: time
    timezone: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_created_count: int | None
    version: int
    updated_at: datetime
    sentinel_slots: int
    can_run: bool


class SentinelRuleCommand(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=3, max_length=80)
    kind: SentinelKind
    threshold_hours: int = Field(ge=0, le=720)
    enabled: bool
    interval_minutes: SentinelInterval
    start_time_local: time
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("start_time_local")
    @classmethod
    def minute_precision(cls, value: time) -> time:
        return SentinelScheduleCommand.minute_precision(value)

    @field_validator("title", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("text_required")
        return value


class SentinelCatalog(BaseModel):
    items: list[SentinelSchedule]
    sentinel_slots: int
    active_count: int
    timezone: str


class SentinelArchiveCommand(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("reason_required")
        return value
