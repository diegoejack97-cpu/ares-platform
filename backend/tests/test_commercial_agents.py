import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.agents.commercial_contracts import (
    CommercialConfig,
    PortfolioRanking,
    PortfolioRequest,
    RankedCandidate,
    validate_commercial,
)
from ares.agents.specialists import SpecialistInput
from ares.connectors.models import CRMCapabilities
from ares.decision.models import ActionDraft
from ares.decision.policy import PolicyEngine


def test_value_requires_explicit_currency_and_browser_cannot_select_actor():
    with pytest.raises(ValidationError):
        PortfolioRequest(criterion="value")
    with pytest.raises(ValidationError):
        PortfolioRequest.model_validate({"actor_id": str(uuid4())})
    assert PortfolioRequest(criterion="value", currency="BRL").currency == "BRL"


def test_proactive_requires_proposal_and_calendar_rejects_invalid_timezone():
    with pytest.raises(ValidationError):
        CommercialConfig(expected_version=0, proactive_enabled=True, reason="Synthetic setting")
    with pytest.raises(ValidationError):
        CommercialConfig.model_validate(
            {
                "expected_version": 0,
                "calendar": {"timezone": "invalid/timezone"},
                "reason": "Synthetic setting",
            }
        )


def test_model_cannot_rank_unknown_or_duplicate_opportunity():
    id = str(uuid4())
    payload = SpecialistInput(
        context_ref=uuid4(), content_hash="test", content=json.dumps({"id": id}), evidence_refs=[id]
    )
    item = RankedCandidate(opportunity_id=id, reason="Evidence available.", evidence_refs=[id])
    with pytest.raises(ValueError):
        validate_commercial(
            PortfolioRanking(
                summary="Review available candidates.",
                ranking=[item, item],
                facts=[],
                limitations=[],
            ),
            payload,
        )
    with pytest.raises(ValueError):
        validate_commercial(
            PortfolioRanking(
                summary="Review available candidates.",
                ranking=[item.model_copy(update={"opportunity_id": uuid4()})],
                facts=[],
                limitations=[],
            ),
            payload,
        )


@pytest.mark.parametrize(
    "kind,payload", [("create_task", {"title": "Review"}), ("add_note", {"body": "Review"})]
)
def test_phase7_requires_human_approval_including_notes(kind, payload):
    policy = PolicyEngine()
    action = ActionDraft(action_kind=kind, payload=payload)
    decision = policy.evaluate(action, CRMCapabilities(), human_review=True)
    assert decision.verdict == "require_approval" and decision.required_role == "manager"
    assert decision.policy_version == 2
    assert (
        policy.evaluate(
            ActionDraft(action_kind="update_stage", payload={"stage": "won"}),
            CRMCapabilities(),
            human_review=True,
        ).verdict
        == "deny"
    )
