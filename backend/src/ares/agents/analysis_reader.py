"""Read only validated/current specialist runs; caller must authorize the actor."""
# SQL statements remain complete for review.
# ruff: noqa: E501

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg

from ares.agents.catalog import SPECIALIST_HASH, SPECIALIST_SEQUENCE, SPECIALIST_VERSION
from ares.agents.specialists import (
    DiagnosisAnalysis,
    SpecialistInput,
    TriageAnalysis,
    validate_grounding,
)
from ares.intelligence.context_builder import (
    ContextBuilder,
    ContextUnavailable,
    encode,
    fingerprint,
)


def analysis_on(
    db: psycopg.Connection[Any], tenant: UUID, actor: UUID, opportunity: UUID
) -> dict[str, Any]:
    flag = db.execute(
        "select enabled,specialists_enabled from public.agent_routines where tenant_id=%s and routine_id='context-analysis'",
        (tenant,),
    ).fetchone()
    result: dict[str, Any] = {
        "enabled": bool(flag and flag["enabled"] and flag["specialists_enabled"]),
        "state": "not_requested",
        "triage": None,
        "diagnosis": None,
        "source": "Context Builder / regras ARES",
        "workflow_id": None,
        "valid_until": None,
    }
    if not result["enabled"]:
        result["state"] = "disabled"
        return result
    capacity = db.execute(
        "select agent_slots from public.tenant_quotas where tenant_id=%s", (tenant,)
    ).fetchone()
    if not capacity or capacity["agent_slots"] < 2:
        result["state"] = "capacity_missing"
        return result
    workflow = db.execute(
        "select * from public.agent_workflows where tenant_id=%s and actor_id=%s and opportunity_id=%s and definition_version=%s order by created_at desc,id limit 1",
        (tenant, actor, opportunity, SPECIALIST_VERSION),
    ).fetchone()
    if not workflow:
        return result
    result.update(
        state=workflow["status"],
        workflow_id=str(workflow["id"]),
        valid_until=workflow["analysis_valid_until"],
        error_code=workflow["error_code"],
        source_fingerprint=workflow["source_fingerprint"],
    )
    if workflow["status"] != "succeeded":
        return result
    try:
        source = ContextBuilder.specialist_projection_on(db, tenant, opportunity)
        if (
            workflow["definition_hash"] != SPECIALIST_HASH
            or fingerprint(workflow["source_content_json"]) != workflow["source_content_hash"]
            or workflow["analysis_valid_until"] <= datetime.now(UTC)
            or source["relevant_hash"] != workflow["source_fingerprint"]
        ):
            result["state"] = "stale"
            return result
        runs = db.execute(
            "select agent_name,output_json,id from public.agent_runs where tenant_id=%s and workflow_id=%s and status='succeeded' order by depth",
            (tenant, workflow["id"]),
        ).fetchall()
        if len(runs) < 2:
            result["state"] = "human_review"
            return result
        if [run["agent_name"] for run in runs] != list(SPECIALIST_SEQUENCE):
            result["state"] = "stale"
            return result
        triage = TriageAnalysis.model_validate(runs[0]["output_json"])
        diagnosis = DiagnosisAnalysis.model_validate(runs[1]["output_json"])
        payload = SpecialistInput(
            context_ref=workflow["context_ref"],
            content_hash=workflow["source_content_hash"],
            content=encode(workflow["source_content_json"]),
            evidence_refs=source["evidence_refs"],
        )
        validate_grounding(triage, payload)
        validate_grounding(diagnosis, payload)
    except (ContextUnavailable, ValueError):
        result["state"] = "stale"
        return result
    result.update(
        state="ready",
        triage=triage.model_dump(mode="json"),
        diagnosis=diagnosis.model_dump(mode="json"),
        context_ref=str(workflow["context_ref"]),
        content_hash=source["content_hash"],
        run_ids=[str(row["id"]) for row in runs],
        evidence_refs=source["evidence_refs"],
        truncated=source["truncated"],
        facts=workflow["source_content_json"],
    )
    return result
