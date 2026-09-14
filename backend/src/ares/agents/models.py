from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AgentMetrics(BaseModel):
    agent_name: str
    agent_version: str
    generation_mode: Literal["agno_openai", "deterministic_fallback"]
    model_id: str | None
    runs: int
    running: int
    succeeded: int
    degraded: int
    failed: int
    latency_samples: int
    latency_p95_ms: float | None
    last_run_at: datetime
    cost_usd: float | None
    cost_status: Literal["not_instrumented", "partial", "calculated"]
    usage_samples: int = 0
    cost_samples: int = 0
    not_called: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    autonomy: Literal["proposal_only", "read_only"]


class AgentWindow(BaseModel):
    since: datetime
    until: datetime
    days: int


class AgentSummary(BaseModel):
    items: list[AgentMetrics]
    window: AgentWindow
    source: str
    freshness_at: datetime
    latency_definition: Literal["run_wall_time_ms"]
    limitations: list[str]
