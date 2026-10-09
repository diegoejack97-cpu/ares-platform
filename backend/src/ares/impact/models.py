from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ImpactWindow(BaseModel):
    since: datetime
    until: datetime
    days: int


class ImpactCounts(BaseModel):
    at_risk: int
    worked: int


class ImpactAmount(BaseModel):
    currency: str | None
    observations: int
    synthetic_observations: int
    sales_observed: int
    recovered: int
    sale_value: Decimal | None
    ares_influenced_value: Decimal | None
    incremental_value: Decimal | None
    freshness_at: datetime | None


class ImpactCost(BaseModel):
    runs: int
    measured_runs: int
    cost_usd: Decimal | None


class ImpactSummary(BaseModel):
    window: ImpactWindow
    counts: ImpactCounts
    amounts: list[ImpactAmount]
    ai_cost: ImpactCost
    source: str
    computed_at: datetime
    definitions: list[str]


class ImpactIntervention(BaseModel):
    intervention_id: UUID
    opportunity_id: UUID
    correlation_id: UUID
    status: str
    state_before_ref: UUID
    state_after_ref: UUID | None
    created_at: datetime
    closed_at: datetime | None
    result_type: str | None
    sale_value: Decimal | None
    ares_influenced_value: Decimal | None
    incremental_value: Decimal | None
    currency: str | None
    attribution_level: str | None
    attribution_method: str | None
    observed_at: datetime | None


class ImpactPage(BaseModel):
    items: list[ImpactIntervention]
    next_cursor: UUID | None
