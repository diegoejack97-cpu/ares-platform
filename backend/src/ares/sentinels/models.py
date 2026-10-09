"""Typed, tenant-scoped schedules for bounded sentinel rule templates."""

from datetime import datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SentinelInterval = Literal[1, 5, 15, 30, 60, 120, 360, 720, 1440]
SentinelKind = Literal["sla_overdue", "unassigned", "stale"]


class SentinelCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stages: list[Literal["new", "qualification", "proposal", "negotiation", "won", "lost"]] = Field(
        default_factory=list, max_length=6
    )
    owner_user_id: UUID | None = None
    min_value: Decimal | None = Field(default=None, ge=0, le=10**12)
    max_value: Decimal | None = Field(default=None, ge=0, le=10**12)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    risk_types: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("risk_types")
    @classmethod
    def risks(cls, value: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item) for item in value):
            raise ValueError("invalid_risk_type")
        return sorted(set(value))

    @model_validator(mode="after")
    def money(self) -> "SentinelCriteria":
        if (self.min_value is not None or self.max_value is not None) and not self.currency:
            raise ValueError("currency_required_for_value")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("value_range_invalid")
        self.stages = sorted(set(self.stages))
        return self


class SentinelCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days_of_week: list[int] = Field(
        default_factory=lambda: list(range(7)), min_length=1, max_length=7
    )
    timezone: str | None = Field(default=None, max_length=80)
    end_time_local: time | None = None
    execution_times: list[time] = Field(default_factory=list, max_length=24)

    @field_validator("days_of_week")
    @classmethod
    def days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("invalid_weekday")
        return sorted(set(value))

    @field_validator("timezone")
    @classmethod
    def zone(cls, value: str | None) -> str | None:
        if value:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("invalid_timezone") from error
        return value

    @field_validator("end_time_local")
    @classmethod
    def end(cls, value: time | None) -> time | None:
        return SentinelScheduleCommand.minute_precision(value) if value else None

    @field_validator("execution_times")
    @classmethod
    def slots(cls, value: list[time]) -> list[time]:
        return sorted(set(SentinelScheduleCommand.minute_precision(item) for item in value))


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
    criteria: SentinelCriteria = Field(default_factory=SentinelCriteria)
    calendar: SentinelCalendar = Field(default_factory=SentinelCalendar)
    interpret_with_ai: bool = False
    last_error_code: str | None = None
    last_matched_count: int | None = None


class SentinelRuleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=3, max_length=80)
    kind: SentinelKind
    threshold_hours: int = Field(ge=0, le=720)
    enabled: bool
    interval_minutes: SentinelInterval
    start_time_local: time
    reason: str = Field(min_length=3, max_length=500)
    criteria: SentinelCriteria = Field(default_factory=SentinelCriteria)
    calendar: SentinelCalendar = Field(default_factory=SentinelCalendar)
    interpret_with_ai: bool = False

    @model_validator(mode="after")
    def unambiguous(self) -> "SentinelRuleCommand":
        end = self.calendar.end_time_local
        if end and end <= self.start_time_local:
            raise ValueError("window_must_end_same_day_after_start")
        if self.calendar.execution_times:
            if self.interval_minutes != 1440:
                raise ValueError("explicit_times_cannot_combine_with_interval")
            if any(
                slot < self.start_time_local or (end and slot > end)
                for slot in self.calendar.execution_times
            ):
                raise ValueError("execution_time_outside_window")
        if self.kind == "unassigned" and self.criteria.owner_user_id:
            raise ValueError("unassigned_cannot_filter_owner")
        return self

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


class NotificationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    action: Literal["read", "unread", "archive", "restore"]
