"""Grounding and independent provider schemas without external calls."""

import json
from uuid import uuid4

import pytest

from ares.agents.catalog import (
    CATALOG,
    CATALOG_HASH,
    SEQUENCE,
    SPECIALIST_VERSION,
    catalog_hash,
    digest,
    validate_step,
)
from ares.agents.contracts import AnalysisInput
from ares.agents.specialists import (
    DiagnosisAnalysis,
    FactClaim,
    Hypothesis,
    SpecialistInput,
    TriageAnalysis,
    validate_grounding,
)
from ares.decision.model_output import ModelFollowupOutput, ModelRecommendationOutput


def input_():
    return SpecialistInput(
        context_ref=uuid4(),
        content_hash="synthetic",
        content=json.dumps({"deal": {"id": "synthetic-deal", "value": 0, "date": "2026-10-08"}}),
        evidence_refs=["synthetic-event"],
    )


def triage(**changes):
    return TriageAnalysis.model_validate(
        {
            "summary": "Negócio disponível para análise humana.",
            "category": "commercial_risk",
            "proposed_urgency": "high",
            "route": "diagnosis",
            "facts": [{"path": "/deal/value", "value": "0"}],
            "evidence_refs": ["synthetic-event"],
            "limitations": [],
            "needs_human_review": True,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"facts": [{"path": "/deal/value", "value": "999"}]}, "agent_fact_invalid"),
        ({"facts": [{"path": "/other/value", "value": "0"}]}, "agent_fact_invalid"),
        ({"evidence_refs": ["invented"]}, "agent_evidence_invalid"),
        ({"summary": "Valor 999 disponível"}, "agent_literal_invalid"),
        ({"summary": "Fechamento previsto em 2027-01-01"}, "agent_literal_invalid"),
        ({"facts": [], "needs_human_review": False}, "agent_ungrounded_conclusion"),
    ],
)
def test_invented_fact_reference_number_date_and_unqualified_conclusion_fail(changes, code):
    with pytest.raises(ValueError, match=code):
        validate_grounding(triage(**changes), input_())


def test_zero_and_real_date_are_valid_and_hypotheses_have_separate_evidence():
    validate_grounding(triage(), input_())
    output = DiagnosisAnalysis(
        summary="Revisão necessária, com hipóteses a confirmar.",
        facts=[FactClaim(path="/deal/date", value="2026-10-08")],
        hypotheses=[
            Hypothesis(
                explanation="Pode haver ausência de contato; confirmar com vendedor.",
                supporting_refs=["synthetic-event"],
                contrary_refs=[],
                missing_information=["Resposta fora do CRM não disponível."],
            )
        ],
        evidence_refs=["synthetic-event"],
        limitations=[],
        needs_human_review=True,
    )
    validate_grounding(output, input_())
    with pytest.raises(ValueError, match="agent_evidence_invalid"):
        validate_grounding(
            output.model_copy(
                update={
                    "hypotheses": [
                        output.hypotheses[0].model_copy(update={"contrary_refs": ["invented"]})
                    ]
                }
            ),
            input_(),
        )


def test_legacy_definitions_and_provider_schema_remain_distinct():
    assert digest({name: CATALOG[name].definition_hash for name in SEQUENCE}) == CATALOG_HASH
    assert CATALOG[SEQUENCE[0]].input_schema is AnalysisInput
    assert catalog_hash(SPECIALIST_VERSION) != CATALOG_HASH
    assert (
        validate_step("opportunity-triage", 0, (), SPECIALIST_VERSION).output_schema
        is TriageAnalysis
    )
    assert "triage" not in ModelFollowupOutput.model_json_schema()["properties"]
    assert "triage" in ModelRecommendationOutput.model_json_schema()["properties"]


def test_followup_uses_independent_triage_without_model_reclassification(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    from ares.decision.model_factory import RecommendationModelFactory

    expected = {
        "urgency": "high",
        "reason": "Triagem validada e independente.",
        "evidence_refs": ["synthetic-event"],
    }

    class Budget:
        def reserve(self, *args):
            return SimpleNamespace(allowed=True)

    class Agent:
        def __init__(self, **kwargs):
            assert kwargs["output_schema"] is ModelFollowupOutput

        def run(self, prompt):
            assert json.loads(prompt)["validated_triage"] == expected
            return SimpleNamespace(
                content={
                    "recommended_action": {
                        "action_kind": "create_task",
                        "payload": {"title": "Revisar negócio"},
                    },
                    "rationale": "Solicitar revisão humana do próximo passo.",
                    "confidence": 0.5,
                    "alternatives": [
                        {
                            "label": "Registrar nota",
                            "action": {
                                "action_kind": "add_note",
                                "payload": {"body": "Revisão humana pendente"},
                            },
                            "tradeoff": "Não cria um prazo.",
                        }
                    ],
                    "contraindication": None,
                },
                metrics=None,
            )

    monkeypatch.setattr("ares.decision.model_factory.Agent", Agent)
    factory = RecommendationModelFactory(
        api_key="synthetic-key",
        model_id="gpt-5-mini",
        budget_guard=Budget(),
        estimated_cost_usd=Decimal("0.01"),
    )
    result = factory.generate(uuid4(), {"validated_triage": expected})
    assert result.output_schema_version == "recommendation.v2"
    assert result.output.triage.model_dump() == expected and result.status == "succeeded"
