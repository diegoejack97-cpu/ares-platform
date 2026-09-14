from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class UsageObservation:
    status: str = "unavailable"
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cost_usd: Decimal | None = None
    pricing_version: str | None = None


def observe(metrics: Any, model_id: str) -> UsageObservation:
    """Only provider counters, never prompt estimates or historical default zeros."""
    values = [
        getattr(metrics, key, None)
        for key in ("input_tokens", "output_tokens", "cache_read_tokens")
    ]
    if any(type(value) is not int or value < 0 for value in values):
        return UsageObservation(model_id=model_id)
    incoming, outgoing, cached = cast(list[int], values)
    if incoming <= 0 or cached > incoming:
        return UsageObservation(model_id=model_id)
    cost, version = None, None
    # Standard text tariff snapshot: https://developers.openai.com/api/docs/models/gpt-5-mini
    # Cached tokens are a subset of input; reasoning tokens are already included in output.
    if model_id in {"gpt-5-mini", "gpt-5-mini-2025-08-07"}:
        cost = (
            (incoming - cached) * Decimal("0.25")
            + cached * Decimal("0.025")
            + outgoing * Decimal("2")
        ) / Decimal(1_000_000)
        version = "openai-standard-text-2026-09-14"
    return UsageObservation("observed", model_id, incoming, outgoing, cached, cost, version)


def record_usage(
    database_url: str, tenant: UUID, run_id: UUID, observation: UsageObservation
) -> None:
    # Commit usage before downstream recommendation/policy writes can fail.
    with psycopg.connect(database_url) as db:
        record_usage_on(db, tenant, run_id, observation)


def record_usage_on(
    db: psycopg.Connection[Any], tenant: UUID, run_id: UUID, observation: UsageObservation
) -> None:
    inserted = db.execute(
        "insert into public.model_usage(tenant_id,run_id,model_id,status,input_tokens,"
        "output_tokens,cached_input_tokens,cost_usd,pricing_version) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id,run_id) do nothing "
        "returning id",
        (
            tenant,
            run_id,
            observation.model_id,
            observation.status,
            observation.input_tokens,
            observation.output_tokens,
            observation.cached_input_tokens,
            observation.cost_usd,
            observation.pricing_version,
        ),
    ).fetchone()
    if inserted and observation.cost_usd is not None:
        db.execute(
            "insert into public.ai_usage_ledger(id,tenant_id,correlation_id,intervention_id,"
            "model,input_tokens,output_tokens,cost_usd) "
            "select %s,tenant_id,correlation_id,intervention_id,%s,%s,%s,%s "
            "from public.agent_runs where tenant_id=%s and id=%s",
            (
                next(iter(inserted.values())) if isinstance(inserted, dict) else inserted[0],
                observation.model_id,
                observation.input_tokens,
                observation.output_tokens,
                observation.cost_usd,
                tenant,
                run_id,
            ),
        )
