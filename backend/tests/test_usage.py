from decimal import Decimal
from types import SimpleNamespace

import pytest

from ares.ai.usage import observe
from ares.decision.model_factory import RecommendationModelFactory


def metrics(incoming=1000, outgoing=200, cached=400):
    return SimpleNamespace(input_tokens=incoming, output_tokens=outgoing, cache_read_tokens=cached)


def test_usage_prices_cache_once_and_preserves_unknown_model():
    observed = observe(metrics(), "gpt-5-mini")
    assert observed.cost_usd == Decimal("0.00056")
    assert observed.input_tokens == 1000 and observed.output_tokens == 200
    assert observed.pricing_version == "openai-standard-text-2026-09-14"
    unknown = observe(metrics(), "unknown-model")
    assert unknown.status == "observed" and unknown.cost_usd is None


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


def test_no_key_does_not_call_provider_or_budget():
    factory = RecommendationModelFactory(
        api_key="", model_id="gpt-5-mini", budget_guard=None, estimated_cost_usd=Decimal("0.01")
    )
    result = factory.generate(None, {})
    assert result.usage.status == "not_called"
    assert result.usage.cost_usd is None
