from decimal import Decimal

from ares.connectors.models import CRMCapabilities
from ares.decision.model_factory import SYSTEM_RULES, RecommendationModelFactory
from ares.decision.models import ActionDraft
from ares.decision.policy import PolicyEngine


class UnusedBudgetGuard:
    def check(self, *_args: object) -> None:
        raise AssertionError("budget must not be queried without an API key")


def test_action_draft_discards_model_supplied_target() -> None:
    draft = ActionDraft(
        action_kind="create_task",
        payload={"title": "Follow-up", "target": "wrong", "deal_id": "wrong"},
    )
    assert draft.payload == {"title": "Follow-up"}


def test_policy_has_three_deterministic_verdicts() -> None:
    policy = PolicyEngine()
    capabilities = CRMCapabilities()
    assert (
        policy.evaluate(
            ActionDraft(action_kind="add_note", payload={"body": "x"}), capabilities
        ).verdict
        == "allow"
    )
    assert (
        policy.evaluate(
            ActionDraft(action_kind="create_task", payload={"title": "x"}), capabilities
        ).verdict
        == "require_approval"
    )
    assert (
        policy.evaluate(
            ActionDraft(action_kind="update_stage", payload={"stage": "won"}), capabilities
        ).verdict
        == "deny"
    )


def test_missing_provider_capability_is_denied() -> None:
    result = PolicyEngine().evaluate(
        ActionDraft(action_kind="create_task", payload={"title": "Follow-up"}),
        CRMCapabilities(create_task=False),
    )
    assert result.verdict == "deny"
    assert "disable_action_in_ui" in result.obligations


def test_no_key_degrades_without_model_call_or_causal_claim() -> None:
    factory = RecommendationModelFactory(
        api_key="",
        model_id="gpt-5-mini",
        budget_guard=UnusedBudgetGuard(),  # type: ignore[arg-type]
        estimated_cost_usd=Decimal("0.01"),
    )
    result = factory.generate(
        "tenant",
        {
            "opportunity": {"priority": 0, "score": 0.91},
            "facts": {"deal": {"title": "Conta X"}, "signals": []},
        },
    )
    assert result.generation_mode == "deterministic_fallback"
    assert result.status == "degraded"
    assert result.output.triage.urgency == "critical"
    assert "incremental" not in result.output.rationale.lower()
    assert any("untrusted" in rule for rule in SYSTEM_RULES)
