"""Grounded specialist schemas and deterministic claim validation, never policy."""

import json
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ares.agents.contracts import EvidenceRef, Limitation, StrictContract


class FactClaim(StrictContract):
    path: str = Field(min_length=1, max_length=240)
    value: str = Field(max_length=500)


class Hypothesis(StrictContract):
    explanation: str = Field(min_length=3, max_length=500)
    supporting_refs: list[EvidenceRef] = Field(max_length=12)
    contrary_refs: list[EvidenceRef] = Field(max_length=12)
    missing_information: list[Limitation] = Field(max_length=6)


class TriageAnalysis(StrictContract):
    schema_version: Literal["triage-output.v1"] = "triage-output.v1"
    summary: str = Field(min_length=3, max_length=1000)
    category: Literal[
        "follow_up", "stalled_deal", "data_gap", "commercial_risk", "insufficient_context"
    ]
    proposed_urgency: Literal["low", "normal", "high", "critical"]
    route: Literal["diagnosis", "human_review"]
    facts: list[FactClaim] = Field(max_length=12)
    evidence_refs: list[EvidenceRef] = Field(max_length=20)
    limitations: list[Limitation] = Field(max_length=8)
    needs_human_review: bool


class DiagnosisAnalysis(StrictContract):
    schema_version: Literal["diagnosis-output.v1"] = "diagnosis-output.v1"
    summary: str = Field(min_length=3, max_length=1000)
    facts: list[FactClaim] = Field(max_length=12)
    hypotheses: list[Hypothesis] = Field(max_length=4)
    evidence_refs: list[EvidenceRef] = Field(max_length=20)
    limitations: list[Limitation] = Field(max_length=8)
    needs_human_review: bool


class SpecialistInput(StrictContract):
    schema_version: Literal["specialist-input.v1"] = "specialist-input.v1"
    context_ref: UUID
    content_hash: str
    content: str = Field(max_length=12000)
    evidence_refs: list[EvidenceRef] = Field(max_length=20)
    previous: TriageAnalysis | None = None


def scalar(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def leaves(value: object, path: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        return {
            key: leaf
            for name, item in value.items()
            for key, leaf in leaves(
                item, path + "/" + str(name).replace("~", "~0").replace("/", "~1")
            ).items()
        }
    if isinstance(value, list):
        return {
            key: leaf
            for i, item in enumerate(value)
            for key, leaf in leaves(item, path + f"/{i}").items()
        }
    return {path: scalar(value)}


def validate_grounding(
    output: TriageAnalysis | DiagnosisAnalysis, payload: SpecialistInput
) -> None:
    values = leaves(json.loads(payload.content))
    if any(values.get(claim.path) != claim.value for claim in output.facts):
        raise ValueError("agent_fact_invalid")
    refs = set(output.evidence_refs)
    if isinstance(output, DiagnosisAnalysis):
        refs |= {
            ref
            for hypothesis in output.hypotheses
            for ref in hypothesis.supporting_refs + hypothesis.contrary_refs
        }
    if not refs <= set(payload.evidence_refs):
        raise ValueError("agent_evidence_invalid")
    if not output.facts and not output.needs_human_review:
        raise ValueError("agent_ungrounded_conclusion")
    # Exact paths prove structured facts. Literal numeric/date/UUID assertions in
    # narrative must also exist in the evidence; this is not a semantic truth proof.
    allowed = set(re.findall(r"[\w]+(?:[.,:/-][\w]+)*", payload.content))
    narrative = [output.summary, *output.limitations]
    if isinstance(output, DiagnosisAnalysis):
        narrative += [h.explanation for h in output.hypotheses]
        narrative += [text for h in output.hypotheses for text in h.missing_information]
    for text in narrative:
        for token in re.findall(r"[\w]+(?:[.,:/-][\w]+)*", text):
            if any(char.isdigit() for char in token) and token not in allowed:
                raise ValueError("agent_literal_invalid")


def specialist_fallback(
    payload: SpecialistInput, *, diagnosis: bool
) -> TriageAnalysis | DiagnosisAnalysis:
    common: dict[str, Any] = {
        "summary": "Evidências disponíveis para revisão humana; interpretação por IA indisponível.",
        "facts": [],
        "evidence_refs": payload.evidence_refs,
        "limitations": ["Modelo não configurado. Não há diagnóstico por IA validado."],
        "needs_human_review": True,
    }
    if diagnosis:
        return DiagnosisAnalysis(**common, hypotheses=[])
    return TriageAnalysis(
        **common, category="insufficient_context", proposed_urgency="normal", route="human_review"
    )
