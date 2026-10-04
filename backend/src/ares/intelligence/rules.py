from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from ares.intelligence.models import CanonicalEvent, SignalDraft

RULE_VERSION = "m2.1"


def _truthy(value: Any) -> bool:
    return value not in (None, "", False, [], {})


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) and number >= 0 else None


def _days(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _draft(kind: str, rule_id: str, severity: int, **evidence: Any) -> SignalDraft:
    return SignalDraft(
        signal_type=kind,
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        severity=severity,
        evidence=evidence,
    )


def follow_up_overdue(event: CanonicalEvent) -> SignalDraft | None:
    due_at = _iso(event.data.get("next_follow_up_at"))
    explicit = event.data.get("risk") == "follow_up_overdue"
    if explicit or (due_at is not None and due_at < event.occurred_at):
        return _draft(
            "follow_up_overdue", "SIG-FOLLOW-UP-OVERDUE", 5, due_at=due_at, explicit=explicit
        )
    return None


def proposal_stalled(event: CanonicalEvent) -> SignalDraft | None:
    days = _days(event.data.get("days_in_stage"))
    if event.data.get("stage") == "proposal" and days is not None and days >= 5:
        return _draft(
            "proposal_stalled", "SIG-PROPOSAL-STALLED", 4, days_in_stage=days, threshold_days=5
        )
    return None


def missing_next_step(event: CanonicalEvent) -> SignalDraft | None:
    if event.aggregate_type == "deal" and not _truthy(event.data.get("next_step")):
        return _draft("missing_next_step", "SIG-MISSING-NEXT-STEP", 3, field="next_step")
    return None


def unowned_deal(event: CanonicalEvent) -> SignalDraft | None:
    if event.aggregate_type == "deal" and not _truthy(event.data.get("owner_id")):
        return _draft("unowned_deal", "SIG-UNOWNED-DEAL", 4, field="owner_id")
    return None


def high_value_at_risk(event: CanonicalEvent) -> SignalDraft | None:
    value = _number(event.data.get("value"))
    days_since_contact = _days(event.data.get("days_since_contact"))
    has_risk = _truthy(event.data.get("risk")) or (
        days_since_contact is not None and days_since_contact >= 7
    )
    if value is not None and value >= 50_000 and has_risk:
        return _draft("high_value_at_risk", "SIG-HIGH-VALUE-RISK", 5, value=value, threshold=50_000)
    return None


def contact_inactive(event: CanonicalEvent) -> SignalDraft | None:
    days = _days(event.data.get("days_since_contact"))
    if days is not None and days >= 7:
        return _draft(
            "contact_inactive",
            "SIG-CONTACT-INACTIVE",
            4 if days < 14 else 5,
            days=days,
            threshold_days=7,
        )
    return None


def close_date_at_risk(event: CanonicalEvent) -> SignalDraft | None:
    close_at = _iso(event.data.get("expected_close_at"))
    days_since_contact = _days(event.data.get("days_since_contact"))
    if close_at is not None:
        days_left = (close_at - event.occurred_at).total_seconds() / 86_400
        if 0 <= days_left <= 7 and days_since_contact is not None and days_since_contact >= 3:
            return _draft(
                "close_date_at_risk",
                "SIG-CLOSE-DATE-RISK",
                5,
                days_left=round(days_left, 1),
                days_since_contact=days_since_contact,
            )
    return None


def stage_regression(event: CanonicalEvent) -> SignalDraft | None:
    stages = ["lead", "qualified", "discovery", "proposal", "negotiation", "won"]
    previous = event.data.get("previous_stage")
    current = event.data.get("stage")
    if previous in stages and current in stages and stages.index(current) < stages.index(previous):
        return _draft(
            "stage_regression", "SIG-STAGE-REGRESSION", 4, previous_stage=previous, stage=current
        )
    return None


RULES: tuple[Callable[[CanonicalEvent], SignalDraft | None], ...] = (
    follow_up_overdue,
    proposal_stalled,
    missing_next_step,
    unowned_deal,
    high_value_at_risk,
    contact_inactive,
    close_date_at_risk,
    stage_regression,
)


def evaluate(event: CanonicalEvent) -> list[SignalDraft]:
    if event.aggregate_type != "deal":
        return []
    return [draft for rule in RULES if (draft := rule(event)) is not None]
