"""Phase 1 contracts. No client-supplied context, SQL, model, or delegation targets."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EvidenceRef = Annotated[str, Field(min_length=1, max_length=128)]
Limitation = Annotated[str, Field(min_length=1, max_length=500)]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StartAnalysis(StrictContract):
    opportunity_id: UUID
    context_ref: UUID
    idempotency_key: UUID
    purpose: Literal["context_analysis"] = "context_analysis"


class RoutineCommand(StrictContract):
    enabled: bool
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500, pattern=r"\S.*\S")


class AnalysisInput(StrictContract):
    schema_version: Literal["analysis-input.v1"] = "analysis-input.v1"
    context_ref: UUID
    content_hash: str
    content: str = Field(max_length=12000)
    evidence_refs: list[EvidenceRef] = Field(max_length=20)
    previous: "AnalysisOutput | None" = None


class AnalysisOutput(StrictContract):
    schema_version: Literal["analysis-output.v1"] = "analysis-output.v1"
    summary: str = Field(min_length=1, max_length=1200)
    evidence_refs: list[EvidenceRef] = Field(max_length=20)
    limitations: list[Limitation] = Field(max_length=8)
    needs_human_review: bool


class AgentJob(StrictContract):
    schema_version: Literal["agent-job.v1"] = "agent-job.v1"
    workflow_id: UUID
    agent_id: Literal[
        "context-triage", "context-diagnosis", "opportunity-triage", "opportunity-diagnosis"
    ]
    depth: int = Field(ge=0, le=3)
    parent_run_id: UUID | None = None
