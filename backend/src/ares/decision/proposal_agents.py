"""Independent proposal and writing agents; DecisionService remains the only action path."""

# ruff: noqa: E501
import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.agents.catalog import CATALOG
from ares.agents.commercial_contracts import FollowupDraft, RecommendationPlan, validate_commercial
from ares.agents.executor import AgentExecutor, AgnoExecutor
from ares.agents.specialists import SpecialistInput
from ares.ai.quotas import QuotaGuard, estimate_usd
from ares.ai.usage import UsageObservation, record_usage
from ares.decision.models import ActionAlternative, ActionDraft, RecommendationOutput, TriageOutput
from ares.intelligence.context_builder import ContextBuilder, encode, fingerprint


def decision_fingerprint_on(db: psycopg.Connection[Any], tenant: UUID, opportunity: UUID) -> str:
    projection = ContextBuilder.specialist_projection_on(db, tenant, opportunity)
    facts = json.loads(projection["content"])
    facts["opportunity"].pop("state", None)
    deal_version = db.execute(
        "select d.version from public.ares_opportunities o join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id where o.tenant_id=%s and o.id=%s",
        (tenant, opportunity),
    ).fetchone()
    return fingerprint([facts, deal_version["version"] if deal_version else None])


def guard_on(db: psycopg.Connection[Any], tenant: UUID, recommendation: UUID) -> None:
    row = db.execute(
        "select g.*,o.version from public.recommendation_context_guards g join public.ares_opportunities o on o.tenant_id=g.tenant_id and o.id=g.opportunity_id where g.tenant_id=%s and g.recommendation_id=%s for share of o",
        (tenant, recommendation),
    ).fetchone()
    if row is None:
        guarded = db.execute(
            "select 1 from public.recommendations where tenant_id=%s and id=%s and output_schema_version='recommendation.v3'",
            (tenant, recommendation),
        ).fetchone()
        if guarded:
            from ares.decision.service import DecisionConflict

            raise DecisionConflict("recommendation_context_stale")
    if row and (
        row["valid_until"] <= datetime.now(UTC)
        or row["expected_version"] != row["version"]
        or row["relevant_hash"] != decision_fingerprint_on(db, tenant, row["opportunity_id"])
    ):
        from ares.decision.service import DecisionConflict

        raise DecisionConflict("recommendation_context_stale")


class ProposalAgents:
    def __init__(self, url: str, model: str, key: str = "", executor: AgentExecutor | None = None):
        self.url, self.model, self.executor = url, model, executor or AgnoExecutor(key)

    def generate(self, tenant: UUID, context: dict[str, Any]) -> Any:
        from ares.decision.model_factory import ModelResult

        parent = UUID(context["run_id"])
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            row = db.execute(
                "select * from public.agent_runs where tenant_id=%s and id=%s", (tenant, parent)
            ).fetchone()
            assert row
            source = ContextBuilder.specialist_projection_on(db, tenant, row["opportunity_id"])
        input = SpecialistInput(
            context_ref=source["context_ref"],
            content_hash=source["content_hash"],
            content=source["content"],
            evidence_refs=source["evidence_refs"],
        )
        outputs: list[Any] = []
        modes: list[bool] = []
        parent_usage = UsageObservation(status="not_called")
        for index, name in enumerate(("action-recommender", "followup-writer")):
            definition = CATALOG[name]
            run = parent if index == 0 else uuid4()
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                if index:
                    db.execute(
                        "insert into public.agent_runs(id,tenant_id,opportunity_id,context_ref,intervention_id,correlation_id,parent_run_id,agent_name,agent_version,prompt_hash,input_schema_version,output_schema_version,generation_mode,status,definition_hash,checkpoint) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'specialist-input.v1','commercial-output.v1','agno_openai','running',%s,'prepared')",
                        (
                            run,
                            tenant,
                            row["opportunity_id"],
                            input.context_ref,
                            row["intervention_id"],
                            row["correlation_id"],
                            parent,
                            name,
                            definition.version,
                            input.content_hash,
                            definition.definition_hash,
                        ),
                    )
                else:
                    db.execute(
                        "update public.agent_runs set agent_name=%s,agent_version=%s,definition_hash=%s,input_schema_version='specialist-input.v1',output_schema_version='commercial-output.v1',checkpoint='prepared' where tenant_id=%s and id=%s",
                        (name, definition.version, definition.definition_hash, tenant, run),
                    )
            if (
                not QuotaGuard(self.url)
                .reserve(
                    tenant, run, estimate_usd(self.model, len(input.model_dump_json().encode()))
                )
                .allowed
            ):
                record_usage(self.url, tenant, run, UsageObservation(status="not_called"))
                raise ValueError("proposal_budget_exceeded")
            try:
                with psycopg.connect(self.url, row_factory=dict_row) as db:
                    from ares.decision.execution_guard import check_execution_contract

                    check_execution_contract(db, tenant)
                    membership = db.execute(
                        "select m.role::text role,o.owner_user_id,r.recommendations_enabled from public.memberships m join public.ares_opportunities o on o.tenant_id=m.tenant_id and o.id=%s join public.commercial_routines r on r.tenant_id=m.tenant_id where m.tenant_id=%s and m.user_id=%s and m.active for share of m,o,r",
                        (row["opportunity_id"], tenant, context["actor_id"]),
                    ).fetchone()
                    if (
                        not membership
                        or not membership["recommendations_enabled"]
                        or membership["role"] not in {"admin", "manager", "seller"}
                        or (
                            membership["role"] == "seller"
                            and str(membership["owner_user_id"]) != context["actor_id"]
                        )
                    ):
                        raise ValueError("proposal_authority_revoked")
                    current = decision_fingerprint_on(db, tenant, row["opportunity_id"])
                    if current != context["decision_fingerprint"]:
                        record_usage(self.url, tenant, run, UsageObservation(status="not_called"))
                        raise ValueError("proposal_context_stale")
                    db.execute(
                        "update public.agent_runs set checkpoint='dispatched' where tenant_id=%s and id=%s",
                        (tenant, run),
                    )
            except Exception:
                record_usage(self.url, tenant, run, UsageObservation(status="not_called"))
                raise
            usage = UsageObservation()
            try:

                async def execute(step=definition, arguments=input):
                    async with asyncio.timeout(95):
                        return await self.executor.execute(step, arguments, self.model)

                result = asyncio.run(execute())
                usage = result.usage
                result = result.__class__(
                    definition.output_schema.model_validate(result.output),
                    result.usage,
                    result.degraded,
                )
                validate_commercial(result.output, input)
                if index and (
                    not isinstance(result.output, FollowupDraft)
                    or result.output.action_kind != outputs[0].action_kind
                ):
                    raise ValueError("followup_action_changed")
                outputs.append(result.output)
                modes.append(result.degraded)
                with psycopg.connect(self.url, row_factory=dict_row) as db:
                    db.execute(
                        "update public.agent_runs set output_json=%s,status=%s,checkpoint='completed',finished_at=now() where tenant_id=%s and id=%s",
                        (
                            Jsonb(result.output.model_dump(mode="json")),
                            "degraded" if result.degraded else "succeeded",
                            tenant,
                            run,
                        ),
                    )
            except Exception:
                with psycopg.connect(self.url, row_factory=dict_row) as db:
                    db.execute(
                        "update public.agent_runs set status='failed',error_code='proposal_generation_failed',finished_at=now() where tenant_id=%s and id=%s",
                        (tenant, run),
                    )
                raise
            finally:
                record_usage(self.url, tenant, run, usage)
            if index == 0:
                parent_usage = usage
                content = json.loads(source["content"])
                content["plan"] = result.output.model_dump(mode="json")
                input = SpecialistInput(
                    context_ref=input.context_ref,
                    content_hash=fingerprint(content),
                    content=encode(content),
                    evidence_refs=input.evidence_refs,
                )
        plan, draft = outputs
        if not isinstance(plan, RecommendationPlan) or not isinstance(draft, FollowupDraft):
            raise ValueError("proposal_schema_invalid")
        output = RecommendationOutput(
            recommended_action=ActionDraft(
                action_kind=plan.action_kind,
                payload={"title": draft.text[:300], "due_in_hours": draft.due_in_hours}
                if plan.action_kind == "create_task"
                else {"body": draft.text},
            ),
            rationale=plan.rationale,
            confidence=0,
            alternatives=[
                ActionAlternative(
                    label="Revisão humana alternativa",
                    action=ActionDraft(
                        action_kind="add_note",
                        payload={
                            "body": "Revisar evidências e definir próximo passo antes de intervir."
                        },
                    ),
                    tradeoff=text[:300],
                )
                for text in plan.alternatives
            ],
            contraindication="; ".join(plan.contraindications)[:500] or None,
            triage=TriageOutput(
                urgency="normal",
                reason="Proposta sujeita à decisão humana; urgência do Core permanece independente.",
                evidence_refs=input.evidence_refs[:12],
            ),
        )
        context["proposal_plan"] = plan.model_dump(mode="json")
        context["proposal_run_ids"] = [str(parent), str(run)]
        return ModelResult(
            output,
            "deterministic_fallback" if any(modes) else "agno_openai",
            self.model,
            input.content_hash,
            "degraded" if any(modes) else "succeeded",
            usage=parent_usage,
            output_schema_version="recommendation.v3",
        )
