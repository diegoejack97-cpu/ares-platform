from datetime import UTC, datetime, time

import pytest
from pydantic import ValidationError

from ares.sentinels.models import SentinelCalendar, SentinelRuleCommand
from ares.sentinels.scheduling import calendar_allows, next_calendar_at


def command(**changes):
    return SentinelRuleCommand.model_validate(
        {
            "title": "Synthetic sentinel",
            "kind": "sla_overdue",
            "threshold_hours": 0,
            "enabled": True,
            "interval_minutes": 60,
            "start_time_local": "09:00",
            "reason": "Synthetic test",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"criteria": {"min_value": 0}},
        {"criteria": {"currency": "BRL", "min_value": 10, "max_value": 0}},
        {"criteria": {"sql": "select *"}},
        {"calendar": {"days_of_week": []}},
        {"calendar": {"days_of_week": [7]}},
        {"calendar": {"timezone": "invalid/zone"}},
        {"calendar": {"end_time_local": "08:00"}},
        {"calendar": {"execution_times": ["09:00"]}},
        {"interval_minutes": 1440, "calendar": {"execution_times": ["08:00"]}},
        {
            "kind": "unassigned",
            "criteria": {"owner_user_id": "10000000-0000-0000-0000-000000000001"},
        },
    ],
)
def test_ambiguous_rules_are_rejected(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_weekdays_window_and_explicit_times():
    cal = SentinelCalendar(
        days_of_week=[0, 2],
        timezone="America/Sao_Paulo",
        end_time_local=time(17),
        execution_times=[time(9), time(14)],
    )
    assert next_calendar_at(
        datetime(2026, 10, 5, 17, tzinfo=UTC), "UTC", time(9), 1440, cal
    ) == datetime(2026, 10, 7, 12, tzinfo=UTC)
    assert not calendar_allows(datetime(2026, 10, 6, 14, tzinfo=UTC), "UTC", time(9), cal)
    assert not calendar_allows(datetime(2026, 10, 5, 21, tzinfo=UTC), "UTC", time(9), cal)
    assert command(interval_minutes=1440, calendar=cal).calendar.execution_times == [
        time(9),
        time(14),
    ]


def test_dst_gap_and_fold_do_not_duplicate_slots():
    cal = SentinelCalendar(timezone="America/New_York", execution_times=[time(2, 30)])
    assert next_calendar_at(
        datetime(2026, 3, 8, 6, tzinfo=UTC), "UTC", time(0), 1440, cal
    ) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    cal = SentinelCalendar(timezone="America/New_York", execution_times=[time(1, 30)])
    assert next_calendar_at(
        datetime(2026, 11, 1, 5, 31, tzinfo=UTC), "UTC", time(0), 1440, cal
    ) == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
