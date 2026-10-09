"""Observed outcome evaluation. Models cannot write outcomes, money, or policy."""

# ruff: noqa: E501
import asyncio
import json
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field

from ares.agents.contracts import StrictContract
from ares.agents.specialists import FactClaim, SpecialistInput, leaves
from ares.ai.quotas import QuotaGuard, estimate_usd
from ares.ai.usage import UsageObservation, record_usage_on
from ares.auth.models import AuthenticatedUser
from ares.intelligence.context_builder import (
    ContextBuilder,
    ContextUnavailable,
    encode,
    fingerprint,
)


class OutcomeExplanation(StrictContract):
    schema_version: Literal["outcome-evaluation.v1"] = "outcome-evaluation.v1"
    summary: str = Field(min_length=3, max_length=1000)
    facts: list[FactClaim] = Field(max_length=12)
    evidence_refs: list[str] = Field(max_length=20)
    limitations: list[str] = Field(min_length=1, max_length=8)
    next_steps: list[str] = Field(max_length=4)
    causal_conclusion: Literal[False] = False
    needs_human_review: Literal[True] = True


def fallback(payload: SpecialistInput) -> OutcomeExplanation:
    facts = json.loads(payload.content)
    return OutcomeExplanation(
        summary="Resultado observado registrado; a associação com a intervenção não comprova causalidade.",
        facts=[FactClaim(path="/outcome/result_type", value=str(facts["outcome"]["result_type"]))],
        evidence_refs=payload.evidence_refs,
        limitations=[
            "Sem grupo de comparação ou método causal validado.",
            "Interpretação automática indisponível; os fatos abaixo foram calculados pelo sistema.",
        ],
        next_steps=["Revisar a cadeia de evidências antes de decidir uma nova ação."],
    )


def validate(output: OutcomeExplanation, payload: SpecialistInput) -> None:
    facts = leaves(json.loads(payload.content))
    if (
        not output.facts
        or any(facts.get(f.path) != f.value for f in output.facts)
        or not set(output.evidence_refs) <= set(payload.evidence_refs)
    ):
        raise ContextUnavailable("outcome_grounding_invalid")
    # This agent never estimates financial impact. Existing money is shown by the deterministic UI.
    import re

    text = " ".join([output.summary, *output.limitations, *output.next_steps]).lower()
    if re.search(
        r"(gerou|causou|recuperou|garantiu).{0,60}(receita|venda|resultado)|receita incremental|r\$|\bbrl\b",
        text,
    ):
        raise ContextUnavailable("outcome_causal_claim_forbidden")
    allowed = set(re.findall(r"[\w]+(?:[.,:/-][\w]+)*", payload.content))
    for token in re.findall(r"[\w]+(?:[.,:/-][\w]+)*", text):
        if any(char.isdigit() for char in token) and token not in allowed:
            raise ContextUnavailable("outcome_literal_invalid")


class Feedback(StrictContract):
    rating: Literal["helpful", "unhelpful"]
    rationale: str = Field(min_length=8, max_length=500)


class OutcomeService:
    def __init__(self, url: str, model: str = "gpt-5.4", key: str = "", executor: Any = None):
        from ares.agents.executor import AgnoExecutor

        self.url, self.model = url, model
        self.executor = executor or AgnoExecutor(key)

    @staticmethod
    def scope(
        db: psycopg.Connection[Any], user: AuthenticatedUser, intervention: UUID
    ) -> dict[str, Any]:
        role = ContextBuilder.authorize(db, user)
        row = db.execute(
            "select i.*,o.owner_user_id from public.ares_interventions i join public.ares_opportunities o on o.tenant_id=i.tenant_id and o.id=i.opportunity_id where i.tenant_id=%s and i.id=%s and (%s<>'seller' or o.owner_user_id=%s)",
            (user.tenant_id, intervention, role, user.user_id),
        ).fetchone()
        if not row:
            raise ContextUnavailable("outcome_not_found", 404)
        return row

    @staticmethod
    def chain_on(
        db: psycopg.Connection[Any], user: AuthenticatedUser, intervention: UUID
    ) -> dict[str, Any]:
        row = OutcomeService.scope(db, user, intervention)
        config = db.execute(
            "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
        ).fetchone()
        hours = config["observation_hours"] if config else 48
        recommendations = db.execute(
            "select id,status,created_at from public.recommendations where tenant_id=%s and intervention_id=%s order by created_at,id limit 10",
            (user.tenant_id, intervention),
        ).fetchall()
        decisions = db.execute(
            "select id,recommendation_id,verdict,decided_at from public.decisions where tenant_id=%s and intervention_id=%s order by decided_at,id limit 10",
            (user.tenant_id, intervention),
        ).fetchall()
        executions = db.execute(
            "select id,status,started_at,finished_at,created_at,source_ref from public.action_executions where tenant_id=%s and intervention_id=%s order by created_at,id limit 10",
            (user.tenant_id, intervention),
        ).fetchall()
        # Provider result whitelist: arbitrary receipt payloads/PII are never sent to the agent.
        for execution in executions:
            receipt_row = db.execute(
                "select result from public.action_executions where tenant_id=%s and id=%s",
                (user.tenant_id, execution["id"]),
            ).fetchone()
            receipt = (receipt_row["result"] if receipt_row else None) or {}
            execution["provider_confirmation"] = {
                key: receipt[key]
                for key in ("confirmed", "status", "version")
                if key in receipt and isinstance(receipt[key], (bool, int))
            }
        outcome = db.execute(
            "select id,action_execution_id,state_after_ref,result_type,sale_value,ares_influenced_value,incremental_value,currency,attribution_level,attribution_method,observed_at,created_at from public.outcomes where tenant_id=%s and intervention_id=%s order by observed_at desc,created_at desc,id desc limit 1",
            (user.tenant_id, intervention),
        ).fetchone()
        start = next(
            (
                e["finished_at"]
                for e in executions
                if e["status"] == "succeeded" and e["finished_at"]
            ),
            row["created_at"],
        )
        deadline = start + timedelta(hours=hours)
        concurrent_row = db.execute(
            "select count(*) n from public.ares_interventions where tenant_id=%s and opportunity_id=%s and id<>%s and created_at<=%s and (closed_at is null or closed_at>=%s)",
            (user.tenant_id, row["opportunity_id"], intervention, deadline, start),
        ).fetchone()
        concurrent = concurrent_row["n"] if concurrent_row else 0
        before = db.execute(
            "select opportunity_state::text state from public.context_snapshots where tenant_id=%s and id=%s",
            (user.tenant_id, row["state_before_ref"]),
        ).fetchone()
        after_ref = outcome["state_after_ref"] if outcome else row["state_after_ref"]
        after = (
            db.execute(
                "select opportunity_state::text state from public.context_snapshots where tenant_id=%s and id=%s",
                (user.tenant_id, after_ref),
            ).fetchone()
            if after_ref
            else None
        )
        return json.loads(
            encode(
                {
                    "intervention_id": row["id"],
                    "opportunity_id": row["opportunity_id"],
                    "correlation_id": row["correlation_id"],
                    "state_before_ref": row["state_before_ref"],
                    "state_after_ref": after_ref,
                    "before_state": before["state"] if before else None,
                    "after_state": after["state"] if after else None,
                    "recommendations": recommendations,
                    "decisions": decisions,
                    "executions": executions,
                    "outcome": outcome,
                    "window": {"start": start, "end": deadline, "hours": hours},
                    "concurrent_interventions": concurrent,
                    "late_outcome": bool(
                        outcome
                        and (outcome["observed_at"] > deadline or outcome["created_at"] > deadline)
                    ),
                    "state_changed": bool(before and after and before["state"] != after["state"]),
                    "commercial_response_seconds": None,
                    "response_limitation": "Não há evento tipado de resposta do cliente; esse tempo não é estimável.",
                }
            )
        )

    def start(self, user: AuthenticatedUser, intervention: UUID) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = ContextBuilder.authorize(db, user)
            if role == "auditor":
                raise ContextUnavailable("outcome_read_only", 403)
            config = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            if not config or not config["outcomes_enabled"]:
                raise ContextUnavailable("outcome_evaluation_disabled", 403)
            chain = ContextBuilder.outcome_on(db, user, intervention)
            hash = fingerprint(chain)
            existing = db.execute(
                "select * from public.outcome_evaluations where tenant_id=%s and intervention_id=%s and context_hash=%s",
                (user.tenant_id, intervention, hash),
            ).fetchone()
            if existing:
                db.execute(
                    "update public.outcome_evaluations set checked_at=now() where tenant_id=%s and id=%s",
                    (user.tenant_id, existing["id"]),
                )
                return existing
            id = uuid4()
            status = "queued" if chain["outcome"] else "pending"
            row = db.execute(
                "insert into public.outcome_evaluations(id,tenant_id,intervention_id,actor_id,context_hash,facts_json,status) values(%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id,intervention_id,context_hash) do update set context_hash=excluded.context_hash returning *",
                (id, user.tenant_id, intervention, user.user_id, hash, Jsonb(chain), status),
            ).fetchone()
            if row and row["id"] == id and status == "queued":
                db.execute(
                    "insert into public.jobs(tenant_id,kind,payload,correlation_id) values(%s,'outcome.evaluate',%s,%s)",
                    (
                        user.tenant_id,
                        Jsonb({"evaluation_id": str(id)}),
                        UUID(chain["correlation_id"]),
                    ),
                )
            return row or {}

    def latest(self, user: AuthenticatedUser, intervention: UUID) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            chain = ContextBuilder.outcome_on(db, user, intervention)
            row = db.execute(
                "select * from public.outcome_evaluations where tenant_id=%s and intervention_id=%s and context_hash=%s order by created_at desc limit 1",
                (user.tenant_id, intervention, fingerprint(chain)),
            ).fetchone()
            return {
                "state": row["status"]
                if row
                else "pending"
                if not chain["outcome"]
                else "not_requested",
                "evaluation": row,
                "chain": chain,
                "source": "Event Journal / outcomes / execução confirmada",
                "causality": "Associação observada não comprova causalidade.",
            }

    def opportunity(self, user: AuthenticatedUser, opportunity: UUID) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = ContextBuilder.authorize(db, user)
            row = db.execute(
                "select i.id from public.ares_interventions i join public.ares_opportunities o on o.tenant_id=i.tenant_id and o.id=i.opportunity_id where i.tenant_id=%s and i.opportunity_id=%s and (%s<>'seller' or o.owner_user_id=%s) order by i.created_at desc limit 1",
                (user.tenant_id, opportunity, role, user.user_id),
            ).fetchone()
        return (
            self.latest(user, row["id"])
            if row
            else {"state": "no_intervention", "evaluation": None, "chain": None}
        )

    def process(self, tenant: UUID, payload: dict[str, Any]) -> None:
        from ares.agents.catalog import CATALOG

        id = UUID(payload["evaluation_id"])
        run = None
        usage = UsageObservation(status="not_called")
        try:
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                row = db.execute(
                    "select * from public.outcome_evaluations where tenant_id=%s and id=%s for update",
                    (tenant, id),
                ).fetchone()
                if not row or row["status"] not in ("queued", "running"):
                    return
                if row["status"] == "running" or payload.get("recovered"):
                    run = row.get("run_id")
                    usage = UsageObservation()
                    raise ContextUnavailable("outcome_generation_unknown")
                user = AuthenticatedUser(tenant_id=tenant, user_id=row["actor_id"], role="admin")
                if ContextBuilder.authorize(db, user) == "auditor":
                    raise ContextUnavailable("outcome_write_forbidden", 403)
                config = db.execute(
                    "select * from public.knowledge_settings where tenant_id=%s", (tenant,)
                ).fetchone()
                if (
                    not config
                    or not config["outcomes_enabled"]
                    or fingerprint(ContextBuilder.outcome_on(db, user, row["intervention_id"]))
                    != row["context_hash"]
                ):
                    raise ContextUnavailable("outcome_context_stale")
                chain = row["facts_json"]
                if not chain["outcome"]:
                    raise ContextUnavailable("outcome_not_observed")
                # Metadata chain may be large: explicitly cap lists, while hashes use the entire chain.
                projection = {
                    **chain,
                    "recommendations": chain["recommendations"][:3],
                    "decisions": chain["decisions"][:3],
                    "executions": chain["executions"][:3],
                }
                content = encode(projection)
                if len(content.encode()) > 12000:
                    raise ContextUnavailable("outcome_context_too_large")
                refs = [
                    chain["intervention_id"],
                    chain["state_before_ref"],
                    chain["outcome"]["id"],
                ] + ([chain["state_after_ref"]] if chain["state_after_ref"] else [])
                inputs = SpecialistInput(
                    context_ref=UUID(chain["state_before_ref"]),
                    content_hash=fingerprint(projection),
                    content=content,
                    evidence_refs=refs,
                )
                run = uuid4()
                definition = CATALOG["outcome-evaluator"]
                db.execute(
                    "insert into public.agent_runs(id,tenant_id,opportunity_id,context_ref,correlation_id,agent_name,agent_version,definition_hash,prompt_hash,input_schema_version,output_schema_version,generation_mode,status,checkpoint) values(%s,%s,%s,%s,%s,'outcome-evaluator',%s,%s,%s,'specialist-input.v1','outcome-evaluation.v1','agno_openai','running','dispatched')",
                    (
                        run,
                        tenant,
                        UUID(chain["opportunity_id"]),
                        inputs.context_ref,
                        UUID(chain["correlation_id"]),
                        definition.version,
                        definition.definition_hash,
                        inputs.content_hash,
                    ),
                )
                if (
                    not QuotaGuard(self.url)
                    .reserve_on(db, tenant, run, estimate_usd(self.model, len(content.encode())))
                    .allowed
                ):
                    db.commit()
                    raise ContextUnavailable("outcome_budget_exceeded", 429)
                db.execute(
                    "update public.outcome_evaluations set status='running',run_id=%s where tenant_id=%s and id=%s",
                    (run, tenant, id),
                )
            usage = UsageObservation()
            result = asyncio.run(
                asyncio.wait_for(
                    self.executor.execute(definition, inputs, self.model),
                    definition.timeout_seconds,
                )
            )
            usage = result.usage
            output = OutcomeExplanation.model_validate(result.output)
            validate(output, inputs)
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                if ContextBuilder.authorize(db, user) == "auditor":
                    raise ContextUnavailable("outcome_write_forbidden", 403)
                fresh = db.execute(
                    "select * from public.knowledge_settings where tenant_id=%s", (tenant,)
                ).fetchone()
                if (
                    not fresh
                    or not fresh["outcomes_enabled"]
                    or fresh["version"] != config["version"]
                    or fingerprint(ContextBuilder.outcome_on(db, user, row["intervention_id"]))
                    != row["context_hash"]
                ):
                    raise ContextUnavailable("outcome_context_stale")
                record_usage_on(db, tenant, run, usage)
                db.execute(
                    "update public.agent_runs set status=%s,output_json=%s,finished_at=now(),checkpoint='completed' where tenant_id=%s and id=%s",
                    (
                        "degraded" if result.degraded else "succeeded",
                        Jsonb(output.model_dump(mode="json")),
                        tenant,
                        run,
                    ),
                )
                db.execute(
                    "update public.outcome_evaluations set status=%s,explanation_json=%s,finished_at=now() where tenant_id=%s and id=%s",
                    (
                        "degraded" if result.degraded else "ready",
                        Jsonb(output.model_dump(mode="json")),
                        tenant,
                        id,
                    ),
                )
        except Exception as error:
            with psycopg.connect(self.url) as db:
                if run:
                    record_usage_on(db, tenant, run, getattr(error, "usage", usage))
                    db.execute(
                        "update public.agent_runs set status='failed',error_code=%s,finished_at=now() where tenant_id=%s and id=%s",
                        (getattr(error, "code", "outcome_evaluation_failed"), tenant, run),
                    )
                db.execute(
                    "update public.outcome_evaluations set status='failed',error_code=%s,finished_at=now() where tenant_id=%s and id=%s and status in ('queued','running')",
                    (getattr(error, "code", "outcome_evaluation_failed"), tenant, id),
                )

    def feedback(
        self, user: AuthenticatedUser, evaluation: UUID, command: Feedback
    ) -> dict[str, Any]:
        from ares.knowledge.text import safe_text

        reason = safe_text(command.rationale)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = ContextBuilder.authorize(db, user)
            if role == "auditor":
                raise ContextUnavailable("outcome_read_only", 403)
            row = db.execute(
                "select intervention_id from public.outcome_evaluations where tenant_id=%s and id=%s",
                (user.tenant_id, evaluation),
            ).fetchone()
            if not row:
                raise ContextUnavailable("outcome_not_found", 404)
            self.scope(db, user, row["intervention_id"])
            db.execute(
                "insert into public.outcome_feedback(id,tenant_id,evaluation_id,actor_id,rating,rationale) values(%s,%s,%s,%s,%s,%s)",
                (uuid4(), user.tenant_id, evaluation, user.user_id, command.rating, reason),
            )
        return {"recorded": True, "classification": "user_opinion"}

    def publish_episode(
        self, user: AuthenticatedUser, evaluation: UUID, reason: str
    ) -> dict[str, Any]:
        from ares.knowledge.models import DocumentUpload
        from ares.knowledge.service import KnowledgeService

        with psycopg.connect(self.url, row_factory=dict_row) as db:
            KnowledgeService.authority(db, user, True)
            config = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            if not config or not config["enabled"] or not config["episodes_enabled"]:
                raise ContextUnavailable("outcome_episode_disabled", 403)
            row = db.execute(
                "select * from public.outcome_evaluations where tenant_id=%s and id=%s",
                (user.tenant_id, evaluation),
            ).fetchone()
            if not row or row["status"] not in ("ready", "degraded"):
                raise ContextUnavailable("outcome_episode_unverified")
            chain = ContextBuilder.outcome_on(db, user, row["intervention_id"])
            if fingerprint(chain) != row["context_hash"] or not chain["outcome"]:
                raise ContextUnavailable("outcome_context_stale")
            existing = db.execute(
                "select d.id,d.current_version from public.knowledge_documents d join public.knowledge_versions v on v.tenant_id=d.tenant_id and v.document_id=d.id and v.version=d.current_version where d.tenant_id=%s and d.origin_intervention_id=%s and not d.deleted and v.status in ('queued','indexing','ready','lexical_only')",
                (user.tenant_id, row["intervention_id"]),
            ).fetchone()
            if existing:
                return {"document_id": existing["id"], "unchanged": True}
            content = "Episódio observado; associação não comprova causalidade.\n" + encode(
                {
                    key: chain[key]
                    for key in (
                        "intervention_id",
                        "state_before_ref",
                        "state_after_ref",
                        "outcome",
                        "window",
                        "concurrent_interventions",
                        "late_outcome",
                    )
                }
            )
        result = KnowledgeService(self.url).upload(
            user,
            DocumentUpload(
                filename="episode.md",
                title="Episódio observado da intervenção",
                source_label="Event Journal / outcome verificado",
                content=content,
                verified_source=True,
                reason=reason,
                allowed_roles=["admin", "manager"],
                purposes=["chat", "outcome"],
                validity_days=config["retention_days"],
            ),
        )
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            KnowledgeService.authority(db, user, True)
            db.execute(
                "select id from public.outcomes where tenant_id=%s and intervention_id=%s for update",
                (user.tenant_id, row["intervention_id"]),
            ).fetchall()
            if (
                fingerprint(ContextBuilder.outcome_on(db, user, row["intervention_id"]))
                != row["context_hash"]
            ):
                db.execute(
                    "update public.knowledge_versions set status='superseded',error_code='outcome_source_changed' where tenant_id=%s and document_id=%s",
                    (user.tenant_id, result["document_id"]),
                )
                db.commit()
                raise ContextUnavailable("outcome_context_stale")
            db.execute(
                "update public.knowledge_documents set origin_intervention_id=%s where tenant_id=%s and id=%s",
                (row["intervention_id"], user.tenant_id, result["document_id"]),
            )
        return result

    def metrics(self, user: AuthenticatedUser, days: int = 30) -> dict[str, Any]:
        if days not in range(1, 366):
            raise ContextUnavailable("outcome_period_invalid", 422)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = ContextBuilder.authorize(db, user)
            counts = db.execute(
                """with cohort as materialized (select i.* from public.ares_interventions i join public.ares_opportunities o on o.tenant_id=i.tenant_id and o.id=i.opportunity_id where i.tenant_id=%s and i.created_at>=now()-(%s*interval '1 day') and i.created_at<=now() and (%s<>'seller' or o.owner_user_id=%s)), latest as (select distinct on (x.intervention_id) x.* from public.outcomes x join cohort c on c.tenant_id=x.tenant_id and c.id=x.intervention_id order by x.intervention_id,x.observed_at desc,x.created_at desc,x.id desc), states as (select b.opportunity_state before_state,a.opportunity_state after_state from cohort c left join latest x on x.intervention_id=c.id left join public.context_snapshots b on b.tenant_id=c.tenant_id and b.id=c.state_before_ref left join public.context_snapshots a on a.tenant_id=c.tenant_id and a.id=coalesce(x.state_after_ref,c.state_after_ref))
                select (select count(*) from cohort) interventions,(select count(*) from latest) outcomes_observed,
                (select count(*) from public.decisions d join cohort c on c.tenant_id=d.tenant_id and c.id=d.intervention_id) decisions,
                (select count(*) from public.decisions d join cohort c on c.tenant_id=d.tenant_id and c.id=d.intervention_id where d.verdict in ('approved','edited')) approved,
                (select count(*) from public.decisions d join cohort c on c.tenant_id=d.tenant_id and c.id=d.intervention_id where d.verdict='rejected') rejected,
                (select count(*) from public.action_executions e join cohort c on c.tenant_id=e.tenant_id and c.id=e.intervention_id) executions,
                (select count(*) from public.action_executions e join cohort c on c.tenant_id=e.tenant_id and c.id=e.intervention_id where e.status='failed') failed,
                (select count(*) from states where before_state is not null and after_state is not null) pairs,
                (select count(*) from states where before_state is not null and after_state is not null and before_state<>after_state) changed,
                (select count(*) from states where before_state is not null and after_state='closed') resolved""",
                (user.tenant_id, days, role, user.user_id),
            ).fetchone()
            assert counts
            return {
                "period_days": days,
                "source": "Intervenções registradas no período / outcomes",
                "coverage": "Todas as intervenções criadas no período e autorizadas; decisões e execuções vinculadas, resultado mais recente por intervenção.",
                "interventions": counts["interventions"],
                "outcomes_observed": counts["outcomes_observed"],
                "pending": counts["interventions"] - counts["outcomes_observed"],
                "adoption": {
                    "numerator": counts["approved"],
                    "denominator": counts["decisions"],
                    "definition": "Decisões aprovadas ou editadas / decisões registradas",
                },
                "rejection": {
                    "numerator": counts["rejected"],
                    "denominator": counts["decisions"],
                    "definition": "Decisões rejeitadas / decisões registradas",
                },
                "execution_failure": {
                    "numerator": counts["failed"],
                    "denominator": counts["executions"],
                    "definition": "Execuções com status failed / execuções registradas",
                },
                "observed_state_change": {
                    "numerator": counts["changed"],
                    "denominator": counts["pairs"],
                    "definition": "Estado Core diferente entre snapshots / pares disponíveis",
                },
                "risk_resolution": {
                    "numerator": counts["resolved"],
                    "denominator": counts["pairs"],
                    "definition": "Estado Core closed / snapshots posteriores disponíveis; não implica ganho no CRM",
                },
                "response_seconds": None,
                "response_denominator": 0,
                "response_definition": "Sem evento tipado de resposta comercial; não inferir pelo tempo da API.",
                "causal_conclusion": False,
            }

    def scan(self) -> None:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            rows = db.execute(
                "select s.tenant_id,s.updated_by,i.id from public.knowledge_settings s join public.ares_interventions i on i.tenant_id=s.tenant_id join public.memberships m on m.tenant_id=s.tenant_id and m.user_id=s.updated_by and m.active and m.role='admin' left join lateral(select max(checked_at) checked_at from public.outcome_evaluations e where e.tenant_id=i.tenant_id and e.intervention_id=i.id) seen on true where s.outcomes_enabled and i.created_at>now()-interval '365 days' order by seen.checked_at nulls first,i.created_at desc limit 30"
            ).fetchall()
        for row in rows:
            try:
                self.start(
                    AuthenticatedUser(
                        tenant_id=row["tenant_id"], user_id=row["updated_by"], role="admin"
                    ),
                    row["id"],
                )
            except ContextUnavailable:
                continue
