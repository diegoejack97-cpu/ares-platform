"""Supported text models share runtime limits and standard USD tariffs."""

from dataclasses import dataclass
from decimal import Decimal

from agno.models.openai import OpenAIResponses

DEFAULT_MODEL = "gpt-5.4"


@dataclass(frozen=True)
class ModelProfile:
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal
    pricing_version: str
    max_output_tokens: int
    timeout_seconds: int


# https://developers.openai.com/api/docs/models/gpt-5-mini
_MINI = ModelProfile(
    Decimal("0.25"),
    Decimal("0.025"),
    Decimal("2"),
    "openai-standard-text-2026-09-14",
    900,
    45,
)
# https://developers.openai.com/api/docs/models/gpt-5.4
# ARES uses bounded text contexts, below the 272K long-context tariff threshold.
_GPT54 = ModelProfile(
    Decimal("2.50"),
    Decimal("0.25"),
    Decimal("15"),
    "openai-standard-text-2026-09-23",
    4096,
    90,
)
_PROFILES = {
    "gpt-5-mini": _MINI,
    "gpt-5-mini-2025-08-07": _MINI,
    "gpt-5.4": _GPT54,
    "gpt-5.4-2026-03-05": _GPT54,
}


def model_profile(model_id: str) -> ModelProfile:
    try:
        return _PROFILES[model_id]
    except KeyError:
        raise ValueError("model_pricing_unconfigured") from None


def response_model(model_id: str, api_key: str) -> OpenAIResponses:
    profile = model_profile(model_id)
    return OpenAIResponses(
        id=model_id,
        api_key=api_key,
        store=False,
        reasoning_effort="medium",
        max_output_tokens=profile.max_output_tokens,
        timeout=profile.timeout_seconds,
        max_retries=0,
    )
