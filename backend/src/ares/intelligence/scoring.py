from __future__ import annotations

from typing import Any

from ares.intelligence.models import ScoreResult

SCORE_VERSION = "m2.1"


def calculate_score(signals: list[dict[str, Any]], deal_value: float) -> ScoreResult:
    severities = [int(signal["severity"]) for signal in signals]
    maximum = max(severities, default=0)
    severity = (maximum / 5) * 0.45
    multiplicity = min(len(signals) / 5, 1) * 0.10
    urgency_kinds = {"follow_up_overdue", "close_date_at_risk", "proposal_stalled"}
    urgency = min(sum(signal["signal_type"] in urgency_kinds for signal in signals) / 2, 1) * 0.25
    value = min(max(deal_value, 0) / 100_000, 1) * 0.20
    total = round(min(severity + multiplicity + urgency + value, 1), 4)
    priority = 0 if total >= 0.8 else 1 if total >= 0.65 else 2 if total >= 0.45 else 3
    return ScoreResult(
        score_version=SCORE_VERSION,
        total_score=total,
        priority=priority,
        breakdown={
            "severity": {
                "value": round(severity, 4),
                "weight": 0.45,
                "max_signal_severity": maximum,
            },
            "urgency": {"value": round(urgency, 4), "weight": 0.25},
            "deal_value": {"value": round(value, 4), "weight": 0.20, "amount": deal_value},
            "signal_count": {
                "value": round(multiplicity, 4),
                "weight": 0.10,
                "count": len(signals),
            },
        },
    )
