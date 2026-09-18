from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from ares.impact.models import ImpactCost, ImpactSummary


class CommandCenterWindow(BaseModel):
    since: datetime
    until: datetime
    days: int


class CommandCenterScope(BaseModel):
    mode: Literal["tenant", "own"]
    role: str
    owner_user_id: UUID | None


class CommandCenterCapabilities(BaseModel):
    approve: bool
    assign: bool
    fix_connection: bool


class ValueAtRisk(BaseModel):
    currency: str | None
    total: Decimal | None
    count: int
    missing: int


class QueueItem(BaseModel):
    opportunity_id: UUID
    title: str | None
    state: str
    priority: int
    score: Decimal | None
    sla_at: datetime | None
    owner_user_id: UUID | None
    primary_signal_type: str | None
    signal_count: int
    deal_value: Decimal | None
    currency: str | None
    pending_approval_id: UUID | None


class ApprovalItem(BaseModel):
    approval_id: UUID
    opportunity_id: UUID
    title: str | None
    urgency: str | None
    required_role: str
    expires_at: datetime | None
    created_at: datetime


class ApprovalsBlock(BaseModel):
    pending: int
    expiring_within_6h: int
    items_limit: int
    items: list[ApprovalItem]


class FailedActionItem(BaseModel):
    execution_id: UUID
    opportunity_id: UUID
    title: str | None
    action_kind: str | None
    attempts: int
    finished_at: datetime | None
    correlation_id: UUID


class FailedActionsBlock(BaseModel):
    count: int
    items_limit: int
    items: list[FailedActionItem]


class ConnectionItem(BaseModel):
    connection_id: UUID
    provider: str
    status: str
    last_sync_at: datetime | None


class ConnectionsBlock(BaseModel):
    total: int
    degraded: int
    revoked: int
    items: list[ConnectionItem]


class NowBlock(BaseModel):
    open_at_risk: int
    critical: int
    sla_overdue: int
    sla_next_6h: int
    sla_missing: int
    without_owner: int
    awaiting_decision: int
    value_at_risk: list[ValueAtRisk]
    queue: list[QueueItem]
    queue_limit: int
    approvals: ApprovalsBlock
    failed_actions: FailedActionsBlock
    connections: ConnectionsBlock
    freshness_at: datetime | None


class CommandCenterImpact(ImpactSummary):
    # The seller scope cannot see tenant-wide AI cost; None is explicit, never runs=0.
    ai_cost: ImpactCost | None  # type: ignore[assignment]


class TrendSeries(BaseModel):
    key: str
    label: str
    values: list[int]


class TrendsBlock(BaseModel):
    days: list[date]
    series: list[TrendSeries]
    freshness_at: datetime | None


class FunnelStage(BaseModel):
    state: str
    label: str
    reached: int


class FunnelBlock(BaseModel):
    cohort: int
    stages: list[FunnelStage]


class SignalType(BaseModel):
    signal_type: str
    severity: int
    total: int


class SignalCell(BaseModel):
    day: date
    signal_type: str
    count: int


class SignalsBlock(BaseModel):
    total: int
    without_opportunity: int
    days: list[date]
    types: list[SignalType]
    cells: list[SignalCell]
    freshness_at: datetime | None


class HeatmapCell(BaseModel):
    weekday: int
    band: int
    count: int


class HeatmapBlock(BaseModel):
    total: int
    timezone: str
    cells: list[HeatmapCell]


class ActivityItem(BaseModel):
    kind: Literal["state", "decision", "action", "outcome"]
    occurred_at: datetime
    actor_type: str | None
    opportunity_id: UUID | None
    title: str | None
    label: str | None
    detail: str | None
    attribution_level: str | None
    correlation_id: UUID | None


class ActivityBlock(BaseModel):
    limit: int
    truncated: bool
    items: list[ActivityItem]


class CoverageBlock(BaseModel):
    opportunities: int
    opportunities_with_owner: int
    opportunities_with_sla: int
    deals_with_value: int
    signals_with_opportunity: int
    synthetic_outcomes: int
    ai_runs: int | None
    ai_measured_runs: int | None


class MetricDefinition(BaseModel):
    key: str
    label: str
    formula: str
    tables: list[str]
    period: str
    attribution_level: str | None
    attribution: str


class CommandCenterSummary(BaseModel):
    window: CommandCenterWindow
    scope: CommandCenterScope
    capabilities: CommandCenterCapabilities
    now: NowBlock
    impact: CommandCenterImpact
    trends: TrendsBlock
    funnel: FunnelBlock
    signals: SignalsBlock
    heatmap: HeatmapBlock
    activity: ActivityBlock
    coverage: CoverageBlock
    definitions: list[MetricDefinition]
    source: str
    freshness_at: datetime | None
    computed_at: datetime
