from decimal import Decimal
from types import SimpleNamespace

import pytest

from ares.ai.quotas import estimate_usd
from ares.ai.usage import observe
from ares.decision.model_factory import RecommendationModelFactory
from ares.decision.model_output import ModelRecommendationOutput


def metrics(incoming=1000, outgoing=200, cached=400):
    return SimpleNamespace(input_tokens=incoming, output_tokens=outgoing, cache_read_tokens=cached)


def test_usage_prices_cache_once_and_preserves_unknown_model():
    observed = observe(metrics(), "gpt-5-mini")
    assert observed.cost_usd == Decimal("0.00056")
    assert observed.input_tokens == 1000 and observed.output_tokens == 200
    assert observed.pricing_version == "openai-standard-text-2026-09-14"
    unknown = observe(metrics(), "unknown-model")
    assert unknown.status == "observed" and unknown.cost_usd is None


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.4-2026-03-05"])
def test_gpt54_accounts_for_cache_and_reserves_both_chat_calls(model):
    observed = observe(metrics(), model)
    assert observed.cost_usd == Decimal("0.0046")
    assert observed.pricing_version == "openai-standard-text-2026-09-23"
    assert estimate_usd(model, 2000, calls=2) == Decimal("0.17384")


def test_unknown_model_cannot_bypass_budget_reservation():
    with pytest.raises(ValueError, match="model_pricing_unconfigured"):
        estimate_usd("unknown-model", 2000)


@pytest.mark.parametrize(
    "value",
    [
        None,
        metrics(0, 0, 0),
        metrics(-1),
        metrics(cached=2000),
        metrics(incoming=True),
        metrics(outgoing=2.5),
    ],
)
def test_missing_or_invalid_usage_is_not_free(value):
    observed = observe(value, "gpt-5-mini")
    assert observed.status == "unavailable" and observed.cost_usd is None


def test_schema_failure_preserves_paid_usage(monkeypatch):
    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt):
            return SimpleNamespace(content={"invalid": True}, metrics=metrics())

    monkeypatch.setattr("ares.decision.model_factory.Agent", FakeAgent)
    factory = RecommendationModelFactory(
        api_key="synthetic",
        model_id="gpt-5-mini",
        budget_guard=SimpleNamespace(reserve=lambda *args: SimpleNamespace(allowed=True)),
        estimated_cost_usd=Decimal("0.01"),
    )
    result = factory.generate(None, {})
    assert result.status == "degraded"
    assert result.usage.cost_usd == Decimal("0.00056")
    assert result.model_id == "gpt-5-mini"


@pytest.mark.parametrize("title,expected", [("Revisar proposta", "succeeded"), (None, "degraded")])
def test_closed_provider_payload_still_passes_domain_validation(monkeypatch, title, expected):
    class FakeAgent:
        def __init__(self, **kwargs):
            self.schema = kwargs["output_schema"]

        def run(self, prompt):
            action = {
                "action_kind": "create_task",
                "payload": {
                    "title": title,
                    "body": None,
                    "stage": None,
                    "due_in_hours": 24,
                },
            }
            content = self.schema.model_validate(
                {
                    "recommended_action": action,
                    "rationale": "Proposta sem retorno confirmado.",
                    "confidence": 0.8,
                    "alternatives": [
                        {
                            "label": "Revisar contexto",
                            "action": action,
                            "tradeoff": "Exige revisao humana antes do contato.",
                        }
                    ],
                    "contraindication": None,
                    "triage": {
                        "urgency": "normal",
                        "reason": "Verificar dados",
                        "evidence_refs": [],
                    },
                }
            )
            return SimpleNamespace(content=content, metrics=metrics())

    schema = ModelRecommendationOutput.model_json_schema()
    payload = schema["$defs"]["ActionPayload"]
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == set(payload["properties"])
    assert "target" not in payload["properties"] and "deal_id" not in payload["properties"]
    monkeypatch.setattr("ares.decision.model_factory.Agent", FakeAgent)
    factory = RecommendationModelFactory(
        api_key="synthetic",
        model_id="gpt-5.4",
        budget_guard=SimpleNamespace(reserve=lambda *args: SimpleNamespace(allowed=True)),
        estimated_cost_usd=Decimal("0.01"),
    )
    result = factory.generate(None, {})
    assert result.status == expected
    if expected == "succeeded":
        assert result.output.recommended_action.payload == {
            "title": "Revisar proposta",
            "due_in_hours": 24,
        }
    else:
        assert result.error_code == "ValidationError"
    assert result.usage.cost_usd == Decimal("0.0046")


def test_no_key_does_not_call_provider_or_budget():
    factory = RecommendationModelFactory(
        api_key="", model_id="gpt-5-mini", budget_guard=None, estimated_cost_usd=Decimal("0.01")
    )
    result = factory.generate(None, {})
    assert result.usage.status == "not_called"
    assert result.usage.cost_usd is None
