from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ares.intelligence.models import CanonicalEvent
from ares.intelligence.rules import RULES, evaluate
from ares.intelligence.scoring import calculate_score
from ares.intelligence.service import validate_transition


def fixture_event(**overrides: object) -> CanonicalEvent:
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "stage": "proposal",
        "previous_stage": "negotiation",
        "risk": "follow_up_overdue",
        "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
        "days_in_stage": 12,
        "next_step": None,
        "owner_id": None,
        "value": 125_000,
        "days_since_contact": 14,
        "expected_close_at": (now + timedelta(days=3)).isoformat(),
    }
    data.update(overrides)
    return CanonicalEvent(
        id=uuid4(),
        tenant_id=uuid4(),
        event_type="deal.updated",
        aggregate_type="deal",
        aggregate_id="deal-test",
        correlation_id=uuid4(),
        occurred_at=now,
        recorded_at=now,
        data=data,
    )


def test_signal_engine_defines_eight_versioned_deterministic_rules() -> None:
    event = fixture_event()
    first = evaluate(event)
    second = evaluate(event)

    assert len(RULES) == 8
    assert {signal.signal_type for signal in first} == {
        "follow_up_overdue",
        "proposal_stalled",
        "missing_next_step",
        "unowned_deal",
        "high_value_at_risk",
        "contact_inactive",
        "close_date_at_risk",
        "stage_regression",
    }
    assert {signal.rule_version for signal in first} == {"m2.1"}
    assert [signal.model_dump() for signal in first] == [signal.model_dump() for signal in second]


def test_non_deal_events_do_not_create_commercial_opportunities() -> None:
    event = fixture_event()
    event.aggregate_type = "activity"
    assert evaluate(event) == []


def test_invalid_crm_numbers_do_not_fail_or_create_numeric_signals() -> None:
    event = fixture_event(
        value="Infinity",
        days_in_stage="n/a",
        days_since_contact="NaN",
        risk="",
        next_follow_up_at=None,
    )
    signals = {signal.signal_type for signal in evaluate(event)}
    assert "high_value_at_risk" not in signals
    assert "proposal_stalled" not in signals
    assert "contact_inactive" not in signals
    assert "close_date_at_risk" not in signals


def test_score_is_decomposed_and_adds_up() -> None:
    signals = [signal.model_dump() for signal in evaluate(fixture_event())]
    score = calculate_score(signals, 125_000)
    assert score.score_version == "m2.1"
    assert score.priority == 0
    assert score.total_score == pytest.approx(
        sum(float(part["value"]) for part in score.breakdown.values())
    )


def test_state_machine_accepts_only_declared_transitions() -> None:
    validate_transition("detected", "prioritized")
    validate_transition("prioritized", "awaiting_decision")
    with pytest.raises(ValueError, match="invalid_opportunity_transition"):
        validate_transition("prioritized", "executing")
