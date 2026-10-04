"""Schedule slots are computed from the tenant's wall clock, never the server clock."""

from datetime import UTC, datetime, time

import pytest
from pydantic import ValidationError

from ares.sentinels.models import SentinelScheduleCommand
from ares.sentinels.service import next_scheduled_at


def test_daily_local_hour_and_next_day() -> None:
    now = datetime(2026, 9, 29, 10, 10, tzinfo=UTC)
    assert next_scheduled_at(now, "America/Sao_Paulo", time(8, 0), 1440) == datetime(
        2026, 9, 29, 11, 0, tzinfo=UTC
    )
    assert next_scheduled_at(
        datetime(2026, 9, 29, 11, 1, tzinfo=UTC),
        "America/Sao_Paulo",
        time(8, 0),
        1440,
    ) == datetime(2026, 9, 30, 11, 0, tzinfo=UTC)


def test_repeated_slots_keep_selected_local_minute() -> None:
    assert next_scheduled_at(
        datetime(2026, 9, 29, 14, 47, tzinfo=UTC),
        "America/Sao_Paulo",
        time(8, 30),
        60,
    ) == datetime(2026, 9, 29, 15, 30, tzinfo=UTC)


def test_schedule_rejects_unsupported_frequency_and_subminute_time() -> None:
    valid = {
        "expected_version": 1,
        "enabled": True,
        "interval_minutes": 60,
        "start_time_local": "08:30:00",
        "reason": "Ajustar frequência",
    }
    assert SentinelScheduleCommand.model_validate(valid).start_time_local == time(8, 30)
    with pytest.raises(ValidationError):
        SentinelScheduleCommand.model_validate({**valid, "interval_minutes": 7})
    with pytest.raises(ValidationError):
        SentinelScheduleCommand.model_validate({**valid, "start_time_local": "08:30:15"})
