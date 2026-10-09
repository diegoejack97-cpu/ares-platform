"""Allowlisted commercial intents; no model-generated SQL or scope grants."""

import re
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

Stage = Literal["new", "qualification", "proposal", "negotiation", "won", "lost"]


class QueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["commercial-query.v1"] = "commercial-query.v1"
    entity: Literal["portfolio", "deal", "opportunity", "sentinel", "intervention"] = "portfolio"
    scope_ref: UUID | None = None
    rule_id: str | None = Field(default=None, min_length=1, max_length=120)
    connection_id: UUID | None = None
    owner_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    references: list[str] | None = Field(default=None, max_length=24)
    stages: list[Stage] = Field(default_factory=list, max_length=6)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    open_only: bool = False
    order: Literal["recent", "value", "lowest_value", "urgency", "deadline", "attractiveness"] = (
        "recent"
    )
    since: datetime | None = None
    until: datetime | None = None
    date_field: Literal["created", "changed"] = "changed"
    fields: list[
        Literal[
            "title",
            "stage",
            "value",
            "currency",
            "owner",
            "priority",
            "opportunity",
            "score",
            "sla",
        ]
    ] = Field(default=["title", "stage", "value", "currency", "priority"], max_length=10)
    sample_limit: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def validate_intent(self) -> "QueryIntent":
        if self.entity in {"deal", "opportunity", "intervention"} and not self.scope_ref:
            raise ValueError("scope_ref_required")
        if self.entity == "sentinel" and not self.rule_id:
            raise ValueError("rule_id_required")
        if self.references is not None and any(not 0 < len(ref) <= 160 for ref in self.references):
            raise ValueError("invalid_record_reference")
        if (self.since is None) != (self.until is None):
            raise ValueError("complete_period_required")
        if self.since is not None and self.until is not None:
            if self.since.tzinfo is None or self.until.tzinfo is None:
                raise ValueError("period_timezone_required")
            if not timedelta(0) < self.until - self.since <= timedelta(days=366):
                raise ValueError("invalid_period")
        return self


def intent_from_question(
    question: str, references: list[str] | None = None, *, timezone: str = "America/Sao_Paulo"
) -> QueryIntent:
    # Compatibility parsing stays deterministic. Models never author SQL or grants.
    from ares.chat.search import STAGE_ALIASES, comparison_criterion, normalize, search_terms

    words = normalize(question)
    criterion = comparison_criterion(question)
    stages = [
        aliases[-1] for stage, aliases in STAGE_ALIASES.items() if re.search(rf"\b{stage}\b", words)
    ]
    terms = [term for term in search_terms(question) if term not in STAGE_ALIASES]
    aggregate = bool(
        re.search(r"\b(total|totais|quantos|quantas|soma|somar|distribuicao|contagem)\b", words)
    )
    explicit = re.search(r'(?:nome|chamad[ao])\s+["“]?([^"”]+)', question, re.I)
    name = explicit.group(1).strip()[:160] if explicit else None
    if not aggregate and not name and terms and references is None:
        name = " ".join(terms)[:160]
    currency = next(
        (code for code in ("BRL", "USD", "EUR") if re.search(rf"\b{code}\b", question, re.I)), None
    )
    now = datetime.now(ZoneInfo(timezone))
    since = None
    if (
        re.search(r"\b(hoje)\b", words)
        and aggregate
        and re.search(r"criad|mud|atualiz|transi|entraram", words)
    ):
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif "esta semana" in words and aggregate:
        since = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif "este mes" in words and aggregate:
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return QueryIntent.model_validate(
        {
            "name": name,
            "references": references,
            "stages": stages,
            "currency": currency,
            "open_only": bool(criterion or re.search(r"\babert[ao]s?\b", words)),
            "order": criterion or "recent",
            "since": since,
            "until": now if since else None,
            "date_field": "created" if "criad" in words else "changed",
        }
    )
