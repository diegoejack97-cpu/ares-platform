"""Offline quality metrics and an explicit reviewed candidate release gate."""

from typing import Any

from ares.intelligence.context_builder import fingerprint

DATASET_VERSION = "commercial-memory-outcomes.synthetic.v1"


def retrieval_metrics(cases: list[dict[str, Any]]) -> dict[str, float]:
    if not cases:
        raise ValueError("evaluation_dataset_empty")
    recalls, precisions, citations = [], [], []
    for case in cases:
        expected = set(case["expected"])
        found = set(case["retrieved"][:5])
        recalls.append(len(found & expected) / len(expected) if expected else float(not found))
        precisions.append(len(found & expected) / len(found) if found else float(not expected))
        citations.append(float(case["citations_valid"]))
    return {
        "recall_at_5": sum(recalls) / len(cases),
        "precision_at_5": sum(precisions) / len(cases),
        "citation_fidelity": sum(citations) / len(cases),
    }


def release_gate(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if (
        baseline.get("dataset_version") != candidate.get("dataset_version")
        or candidate.get("dataset_version") != DATASET_VERSION
        or baseline.get("dataset_hash") != candidate.get("dataset_hash")
        or not candidate.get('dataset_hash')
    ):
        reasons.append("dataset_not_comparable")
    for name, minimum in [
        ("recall_at_5", 0.8),
        ("precision_at_5", 0.8),
        ("citation_fidelity", 1.0),
    ]:
        score = candidate.get("metrics", {}).get(name)
        previous = baseline.get("metrics", {}).get(name)
        if (
            type(score) not in (float, int)
            or type(previous) not in (float, int)
            or not 0 <= score <= 1
            or score < minimum
            or score < previous
        ):
            reasons.append("regression:" + name)
    if (
        candidate.get("isolation_failures") != 0
        or candidate.get("grounding_failures") != 0
        or candidate.get("causal_claims") != 0
    ):
        reasons.append("safety_regression")
    review = candidate.get("review", {})
    if (
        review.get("approved") is not True
        or not review.get("reviewer")
        or not review.get("reviewed_at")
    ):
        reasons.append("human_review_required")
    if not candidate.get("prompt_version") or not candidate.get("model_id"):
        reasons.append("candidate_not_versioned")
    return {"allowed": not reasons, "reasons": reasons, "candidate_hash": fingerprint(candidate)}
