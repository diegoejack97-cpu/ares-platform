"""Closed phase 6/7 contracts. Interpretation never grants execution authority."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ares.agents.contracts import StrictContract
from ares.agents.specialists import FactClaim, SpecialistInput, leaves
from ares.sentinels.models import SentinelCalendar

Criterion = Literal["urgency", "value", "deadline", "attractiveness"]


class PortfolioRequest(StrictContract):
    criterion: Criterion = "urgency"
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def currency_required(self) -> "PortfolioRequest":
        if self.criterion == "value" and not self.currency:
            raise ValueError("value_currency_required")
        return self


class CommercialConfig(PortfolioRequest):
    expected_version: int = Field(ge=0)
    enabled: bool = False
    recommendations_enabled: bool = False
    proactive_enabled: bool = False
    calendar: SentinelCalendar = Field(default_factory=SentinelCalendar)
    cooldown_hours: int = Field(default=24, ge=1, le=168)
    daily_proposal_limit: int = Field(default=3, ge=1, le=20)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def proactive_requires_recommendations(self) -> "CommercialConfig":
        if self.proactive_enabled and (not self.recommendations_enabled or not self.enabled):
            raise ValueError("proactive_requires_recommendations")
        return self


class RankedCandidate(StrictContract):
    opportunity_id: UUID
    reason: str = Field(min_length=3, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=4)


class PortfolioRanking(StrictContract):
    summary: str = Field(min_length=3, max_length=1000)
    ranking: list[RankedCandidate] = Field(max_length=20)
    facts: list[FactClaim] = Field(max_length=12)
    limitations: list[str] = Field(max_length=8)


class CommercialBriefing(StrictContract):
    summary: str = Field(min_length=3, max_length=1000)
    risks: list[str] = Field(max_length=6)
    next_steps: list[str] = Field(max_length=6)
    facts: list[FactClaim] = Field(max_length=12)
    limitations: list[str] = Field(max_length=8)


class RecommendationPlan(StrictContract):
    action_kind: Literal["create_task", "add_note"]
    rationale: str = Field(min_length=8, max_length=800)
    alternatives: list[str] = Field(min_length=1, max_length=3)
    risks: list[str] = Field(max_length=6)
    contraindications: list[str] = Field(max_length=6)
    missing_information: list[str] = Field(max_length=6)
    valid_for_hours: int = Field(ge=1, le=24)
    facts: list[FactClaim] = Field(max_length=12)
    evidence_refs: list[str] = Field(max_length=20)


class FollowupDraft(StrictContract):
    action_kind: Literal["create_task", "add_note"]
    text: str = Field(min_length=3, max_length=1000)
    due_in_hours: int = Field(ge=1, le=168)
    facts: list[FactClaim] = Field(max_length=12)
    evidence_refs: list[str] = Field(max_length=20)


class PortfolioCandidateView(BaseModel):
    id: UUID
    title: str
    value: Decimal | None = None
    currency: str | None = None
    priority: int | None = None
    score: Decimal | None = None
    sla_at: datetime | None = None


class CurrencyTotalView(BaseModel):
    currency: str | None
    records: int
    value: Decimal | None


class PortfolioView(BaseModel):
    state: str
    analysis_id: UUID | None
    can_request: bool
    criterion: Criterion
    currency: str | None
    ranking: PortfolioRanking | None
    briefing: CommercialBriefing | None
    created_at: datetime | None
    valid_until: datetime | None
    context_ref: UUID | None
    run_ids: list[UUID]
    error_code: str | None
    source: str
    total: int
    currency_totals: list[CurrencyTotalView]
    candidates: list[PortfolioCandidateView]
    coverage_note: str
    scope: str


def validate_commercial(output: object, payload: SpecialistInput) -> None:
    values = leaves(json.loads(payload.content))
    claims = getattr(output, "facts", [])
    if any(values.get(claim.path) != claim.value for claim in claims):
        raise ValueError("commercial_fact_invalid")
    refs = set(payload.evidence_refs)
    if not set(getattr(output, "evidence_refs", [])) <= refs:
        raise ValueError("commercial_reference_invalid")
    if isinstance(output, PortfolioRanking):
        ids = [str(item.opportunity_id) for item in output.ranking]
        if len(ids) != len(set(ids)) or not set(ids) <= refs:
            raise ValueError("commercial_candidate_invalid")
        if any(not set(item.evidence_refs) <= refs for item in output.ranking):
            raise ValueError("commercial_reference_invalid")


def commercial_fallback(agent: str, payload: SpecialistInput) -> object:
    facts = json.loads(payload.content)
    limitation = ["Interpretação por IA indisponível; revisão humana necessária."]
    if agent == "portfolio-prioritizer":
        return PortfolioRanking(
            summary="Seleção determinística do banco; não há ranking por IA validado.",
            ranking=[
                RankedCandidate(
                    opportunity_id=item["id"],
                    reason="Candidato selecionado pelo critério declarado no banco.",
                    evidence_refs=[item["id"]],
                )
                for item in facts.get("matches", [])
            ],
            facts=[],
            limitations=limitation,
        )
    if agent == "commercial-analyst":
        return CommercialBriefing(
            summary="Carteira disponível para revisão humana.",
            risks=[],
            next_steps=["Revisar os candidatos e as lacunas antes de propor uma intervenção."],
            facts=[],
            limitations=limitation,
        )
    if agent == "action-recommender":
        return RecommendationPlan(
            action_kind="create_task",
            rationale="Preparar uma tarefa de revisão humana com base no contexto disponível.",
            alternatives=["Registrar uma nota após revisão humana."],
            risks=["Dados de canais externos podem não estar sincronizados."],
            contraindications=["Revisar se já houve contato por canal não sincronizado."],
            missing_information=["Confirmar o próximo passo com o responsável."],
            valid_for_hours=1,
            facts=[],
            evidence_refs=payload.evidence_refs,
        )
    return FollowupDraft(
        action_kind=facts["plan"]["action_kind"],
        text="Revisar os sinais, confirmar o responsável e definir o próximo passo comercial.",
        due_in_hours=24,
        facts=[],
        evidence_refs=payload.evidence_refs,
    )
