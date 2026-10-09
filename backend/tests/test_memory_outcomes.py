import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.agents.specialists import SpecialistInput
from ares.impact.evaluation import OutcomeExplanation, fallback, validate
from ares.intelligence.context_builder import ContextUnavailable, fingerprint
from ares.knowledge.models import DocumentUpload
from ares.knowledge.service import vector
from ares.knowledge.text import chunks, safe_text


@pytest.mark.parametrize(
    "value",
    [
        "senha: muito-secreta",
        "a pessoa@example.invalid",
        "CPF 123.456.789-00",
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN RSA PRIVATE KEY",
        "texto\x00invalido",
    ],
)
def test_reject_sensitive_or_binary(value):
    with pytest.raises(ContextUnavailable):
        safe_text(value)


def test_utf8_chunks_preserve_source():
    text = "ação comercial e negociação\n" * 300
    parts = chunks(text)
    assert "".join(parts) == text
    assert all(len(part.encode()) <= 1800 for part in parts)


def test_formats_and_verification_are_required():
    with pytest.raises(ValidationError):
        DocumentUpload(
            filename="code.py",
            title="documento",
            source_label="sintético",
            content="somente exemplo",
        )


def test_embedding_shape_rejects_nonfinite():
    with pytest.raises(ContextUnavailable):
        vector([float("nan")] * 1536)


def payload():
    facts = {"outcome": {"result_type": "observed_change"}}
    return SpecialistInput(
        context_ref=uuid4(),
        content=json.dumps(facts),
        content_hash=fingerprint(facts),
        evidence_refs=["source"],
    )


def test_result_fallback_is_grounded_and_noncausal():
    output = fallback(payload())
    validate(output, payload())
    assert not output.causal_conclusion


def test_result_rejects_invented_fact():
    result = fallback(payload()).model_copy(update={"facts": []})
    with pytest.raises(ContextUnavailable):
        validate(result, payload())


def test_result_schema_forbids_incremental_claim():
    with pytest.raises(ValidationError):
        OutcomeExplanation(
            summary="inventado",
            facts=[],
            evidence_refs=[],
            limitations=["limite"],
            next_steps=[],
            causal_conclusion=True,
        )
    result = fallback(payload()).model_copy(update={"summary": "A intervenção gerou receita."})
    with pytest.raises(ContextUnavailable):
        validate(result, payload())


def test_release_gate_blocks_regression_and_missing_human_review():
    from ares.agents.quality import DATASET_VERSION, release_gate

    baseline = {
        "dataset_version": DATASET_VERSION,
        "dataset_hash": "synthetic-v1",
        "metrics": {"recall_at_5": 1.0, "precision_at_5": 1.0, "citation_fidelity": 1.0},
    }
    candidate = {
        **baseline,
        "prompt_version": "synthetic.v1",
        "model_id": "synthetic-executor",
        "isolation_failures": 0,
        "grounding_failures": 0,
        "causal_claims": 0,
        "review": {},
    }
    assert not release_gate(baseline, candidate)["allowed"]
    candidate["review"] = {
        "approved": True,
        "reviewer": "synthetic reviewer",
        "reviewed_at": "2026-10-09",
    }
    assert release_gate(baseline, candidate)["allowed"]
    candidate["metrics"] = {**candidate["metrics"], "recall_at_5": 0.9}
    assert not release_gate(baseline, candidate)["allowed"]
