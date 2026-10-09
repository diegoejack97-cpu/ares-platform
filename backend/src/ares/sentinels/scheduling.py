"""Bounded local-calendar scheduling, including DST gaps and ambiguous hours."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ares.sentinels.models import SentinelCalendar


def calendar_allows(now: datetime, timezone: str, start: time, calendar: SentinelCalendar) -> bool:
    if calendar == SentinelCalendar():
        return True
    local = now.astimezone(ZoneInfo(calendar.timezone or timezone))
    return (
        local.weekday() in calendar.days_of_week
        and local.time() >= start
        and (calendar.end_time_local is None or local.time() <= calendar.end_time_local)
    )


def next_calendar_at(
    now: datetime, timezone: str, start: time, interval: int, calendar: SentinelCalendar
) -> datetime:
    if calendar == SentinelCalendar():
        from ares.sentinels.service import next_scheduled_at

        return next_scheduled_at(now, timezone, start, interval)
    zone = ZoneInfo(calendar.timezone or timezone)
    local = now.astimezone(zone)
    end = calendar.end_time_local or time(23, 59)
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in calendar.days_of_week:
            continue
        slots = calendar.execution_times
        if not slots:
            minutes = start.hour * 60 + start.minute
            maximum = end.hour * 60 + end.minute
            slots = [
                time(value // 60, value % 60) for value in range(minutes, maximum + 1, interval)
            ]
        for slot in slots:
            wall = datetime.combine(day, slot)
            candidate = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
            # Skip nonexistent DST hours; use only the first occurrence of repeated hours.
            if candidate.astimezone(zone).replace(tzinfo=None) != wall:
                continue
            if candidate > now.astimezone(UTC):
                return candidate
    raise ValueError("sentinel_calendar_has_no_slot")
