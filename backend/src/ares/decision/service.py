# SQL joins stay one-per-line for audit readability.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.agents.analysis_reader import analysis_on
from ares.ai.budget import AIBudgetGuard
from ares.ai.models import DEFAULT_MODEL
from ares.ai.usage import record_usage
from ares.connectors.provider import CRMProvider
from ares.connectors.resolver import TenantCRMProvider
from ares.decision.authorization import DecisionAuthorizationError, role_can_decide
from ares.decision.execution_guard import (
    ExecutionBlocked,
    check_execution_contract,
    execution_contract,
)
from ares.decision.model_factory import RecommendationModelFactory
from ares.decision.models import ActionDraft, DecideCommand
from ares.decision.policy import PolicyEngine
from ares.decision.proposal_agents import ProposalAgents, decision_fingerprint_on, guard_on


class DecisionConflict(Exception):
    def __init__(self, code: str, current_version: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.current_version = current_version


class DecisionService:
    def __init__(
        self,
        database_url: str,
        tenant_id: UUID,
        provider: CRMProvider,
        *,
        openai_api_key: str = "",
        openai_model: str = DEFAULT_MODEL,
        estimated_cost_usd: Decimal = Decimal("0.01"),
    ) -> None:
        self._database_url = database_url
        self._tenant_id = tenant_id
        self._provider = provider
        self._policy = PolicyEngine()
        self._proposal_agents = ProposalAgents(database_url, openai_model, openai_api_key)
        self._models = RecommendationModelFactory(
            api_key=openai_api_key,
            model_id=openai_model,
            budget_guard=AIBudgetGuard(database_url),
            estimated_cost_usd=estimated_cost_usd,
        )

    def _actor_role(
        self, connection: psycopg.Connection[Any], actor_id: str | None, *, lock: bool = False
    ) -> str | None:
        try:
            actor = UUID(str(actor_id))
        except (ValueError, TypeError):
            return None
        row = connection.execute(
            """
            select m.role::text as role from public.memberships m
            join public.tenants t on t.id = m.tenant_id
            where m.tenant_id = %s and m.user_id = %s and m.active and t.status = 'active'
            """
            + (" for share of m, t" if lock else ""),
            (self._tenant_id, actor),
        ).fetchone()
        return str(row["role"]) if row else None

    def _authorize_request(
        self, connection: psycopg.Connection[Any], opportunity_id: UUID, actor_id: str
    ) -> None:
        role = self._actor_role(connection, actor_id, lock=True)
        if role not in {"admin", "manager", "seller"}:
            raise DecisionAuthorizationError()
        row = connection.execute(
            "select owner_user_id from public.ares_opportunities where tenant_id = %s and id = %s for share",
            (self._tenant_id, opportunity_id),
        ).fetchone()
        if row is None:
            raise ValueError("opportunity_not_found")
        if role == "seller" and str(row["owner_user_id"]) != actor_id:
            raise DecisionAuthorizationError("opportunity_scope_forbidden")
        self._require_contract(connection)

    def _require_contract(self, connection: psycopg.Connection[Any]) -> None:
        try:
            check_execution_contract(connection, self._tenant_id)
        except ExecutionBlocked as error:
            raise DecisionAuthorizationError(error.code) from error

    def _contract_block_reason(self, connection: psycopg.Connection[Any]) -> str | None:
        try:
            check_execution_contract(connection, self._tenant_id)
        except ExecutionBlocked as error:
            return error.code
        return None

    @staticmethod
    def _authorize_decision(role: str | None, actor_id: str, row: dict[str, Any]) -> None:
        if not role_can_decide(role, row.get("approval_required_role")):
            raise DecisionAuthorizationError("approval_role_required")
        if role == "seller" and str(row.get("owner_user_id")) != actor_id:
            raise DecisionAuthorizationError("opportunity_scope_forbidden")

    def _decision_permissions(
        self,
        row: dict[str, Any],
        actor_role: str | None,
        actor_id: str | None,
        execution_block_reason: str | None = None,
    ) -> dict[str, Any]:
        can_decide = False
        expiry = row.get("approval_expires_at", row.get("expires_at"))
        if (
            actor_id
            and execution_block_reason is None
            and row.get("status") == "pending"
            and row.get("approval_status", "pending") == "pending"
            and row.get("policy_verdict") == "require_approval"
            and isinstance(expiry, datetime)
            and expiry > datetime.now(UTC)
        ):
            try:
                self._authorize_decision(actor_role, actor_id, row)
                action = ActionDraft.model_validate(row["recommended_action"])
                policy = self._policy.evaluate(
                    action,
                    self._provider.capabilities(),
                    **(
                        {"human_review": True}
                        if row.get("output_schema_version") == "recommendation.v3"
                        else {}
                    ),
                )
                can_decide = policy.verdict != "deny" and (
                    policy.verdict != "require_approval"
                    or role_can_decide(actor_role, policy.required_role)
                )
            except (DecisionAuthorizationError, ValueError, KeyError):
                pass
        return {**row, "can_decide": can_decide, "execution_block_reason": execution_block_reason}

    async def can_request_recommendation(self, opportunity_id: UUID, actor_id: str) -> bool:
        return await asyncio.to_thread(
            self._can_request_recommendation_sync, opportunity_id, actor_id
        )

    def _can_request_recommendation_sync(self, opportunity_id: UUID, actor_id: str) -> bool:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            try:
                self._authorize_request(connection, opportunity_id, actor_id)
            except (DecisionAuthorizationError, ValueError):
                return False
        return True

    async def create_recommendation(self, opportunity_id: UUID, actor_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.create_recommendation_sync, opportunity_id, actor_id)

    def create_recommendation_sync(self, opportunity_id: UUID, actor_id: str) -> dict[str, Any]:
        correlation_id = uuid4()
        auto_intent_id: UUID | None = None
        analysis: dict[str, Any] = {}
        phase7 = False
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (str(self._tenant_id) + str(opportunity_id) + ":recommendation",),
            )
            self._authorize_request(connection, opportunity_id, actor_id)
            routine = connection.execute(
                "select recommendations_enabled from public.commercial_routines where tenant_id=%s",
                (self._tenant_id,),
            ).fetchone()
            phase7 = bool(routine and routine["recommendations_enabled"])
            capabilities = self._provider.capabilities()
            if phase7 and not (capabilities.create_task or capabilities.add_note):
                raise DecisionConflict("proposal_capability_unavailable")
            if (
                phase7
                and connection.execute(
                    "select 1 from public.agent_runs where tenant_id=%s and opportunity_id=%s and agent_name in ('action-recommender','followup-writer','follow-up+triage') and status='running'",
                    (self._tenant_id, opportunity_id),
                ).fetchone()
            ):
                raise DecisionConflict("recommendation_in_progress")
            existing = connection.execute(
                """
                select r.id as recommendation_id, r.run_id, r.status, r.version,
                  r.intervention_id, r.correlation_id
                from public.recommendations r
                where r.tenant_id = %s and r.opportunity_id = %s and r.status = 'pending'
                order by r.created_at desc limit 1
                """,
                (self._tenant_id, opportunity_id),
            ).fetchone()
            if existing is not None:
                if phase7:
                    try:
                        guard_on(connection, self._tenant_id, existing["recommendation_id"])
                    except DecisionConflict:
                        connection.execute(
                            "update public.recommendations set status='superseded',version=version+1,updated_at=now() where tenant_id=%s and id=%s",
                            (self._tenant_id, existing["recommendation_id"]),
                        )
                        connection.execute(
                            "update public.approval_requests set status='superseded',version=version+1,updated_at=now(),resolved_at=now(),resolved_by='context-revalidation' where tenant_id=%s and recommendation_id=%s",
                            (self._tenant_id, existing["recommendation_id"]),
                        )
                        connection.execute(
                            "update public.ares_interventions set status='cancelled',closed_at=now() where tenant_id=%s and id=%s",
                            (self._tenant_id, existing["intervention_id"]),
                        )
                        existing = None
                if existing is not None:
                    return dict(existing)
            capacity = connection.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s",
                (self._tenant_id,),
            ).fetchone()
            if capacity is not None and capacity["agent_slots"] == 0:
                raise DecisionConflict("agent_capacity_disabled")
            row = connection.execute(
                """
                select o.id, o.state, o.score, o.priority, o.version,
                  c.id as context_ref, c.facts_json, c.citations_json
                from public.ares_opportunities o
                join lateral (
                  select * from public.context_snapshots c
                  where c.tenant_id = o.tenant_id and c.opportunity_id = o.id
                  order by c.snapshot_version desc limit 1
                ) c on true
                where o.tenant_id = %s and o.id = %s
                for update of o
                """,
                (self._tenant_id, opportunity_id),
            ).fetchone()
            if row is None:
                raise ValueError("opportunity_or_context_not_found")
            if row["state"] not in {"prioritized", "awaiting_decision"}:
                raise DecisionConflict("opportunity_not_recommendable", int(row["version"]))
            analysis = analysis_on(connection, self._tenant_id, UUID(actor_id), opportunity_id)
            intervention = connection.execute(
                """
                insert into public.ares_interventions (
                  tenant_id, opportunity_id, correlation_id, state_before_ref,
                  status, source, source_ref
                ) values (%s, %s, %s, %s, 'deciding', 'ares', 'decision-engine:m3.1')
                returning id
                """,
                (self._tenant_id, opportunity_id, correlation_id, row["context_ref"]),
            ).fetchone()
            assert intervention is not None
            run = connection.execute(
                """
                insert into public.agent_runs (
                  tenant_id, intervention_id, opportunity_id, context_ref, correlation_id,
                  agent_name, agent_version, prompt_hash, output_schema_version,
                  generation_mode, status
                ) values (%s, %s, %s, %s, %s, 'follow-up+triage', 'm3.1',
                  'pending', 'recommendation.v1', 'deterministic_fallback', 'running')
                returning id
                """,
                (
                    self._tenant_id,
                    intervention["id"],
                    opportunity_id,
                    row["context_ref"],
                    correlation_id,
                ),
            ).fetchone()
            assert run is not None
            if row["state"] == "prioritized":
                self._transition(
                    connection,
                    opportunity_id,
                    "prioritized",
                    "awaiting_decision",
                    "recommendation_generated",
                    correlation_id,
                    "ares_agent",
                    "decision-engine:m3.1",
                )
                connection.execute(
                    """
                    update public.ares_opportunities
                    set state = 'awaiting_decision', version = version + 1, updated_at = now()
                    where tenant_id = %s and id = %s
                    """,
                    (self._tenant_id, opportunity_id),
                )
        context = {
            "run_id": str(run["id"]),
            "opportunity": {
                "id": str(opportunity_id),
                "score": row["score"],
                "priority": row["priority"],
            },
            "context_ref": str(row["context_ref"]),
            "facts": row["facts_json"],
            "citations": row["citations_json"],
        }
        if analysis.get("state") == "ready":
            context["facts"] = {
                key: value for key, value in analysis["facts"].items() if key != "opportunity"
            }
            triage = analysis["triage"]
            context["validated_triage"] = {
                "urgency": triage["proposed_urgency"],
                "reason": triage["summary"][:400],
                "evidence_refs": triage["evidence_refs"][:12],
            }
            context["analysis_ref"] = {
                "workflow_id": analysis["workflow_id"],
                "source_fingerprint": analysis["source_fingerprint"],
                "run_ids": analysis["run_ids"],
            }
        if phase7:
            context["actor_id"] = actor_id
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                context["decision_fingerprint"] = decision_fingerprint_on(
                    connection, self._tenant_id, opportunity_id
                )
                current = connection.execute(
                    "select version from public.ares_opportunities where tenant_id=%s and id=%s",
                    (self._tenant_id, opportunity_id),
                ).fetchone()
                assert current
                context["expected_opportunity_version"] = current["version"]
            try:
                generated = self._proposal_agents.generate(self._tenant_id, context)
            except Exception:
                with psycopg.connect(self._database_url) as connection:
                    connection.execute(
                        "update public.agent_runs set status='failed',error_code='proposal_generation_failed',finished_at=now() where tenant_id=%s and intervention_id=%s and status='running'",
                        (self._tenant_id, intervention["id"]),
                    )
                    connection.execute(
                        "update public.ares_interventions set status='cancelled',closed_at=now() where tenant_id=%s and id=%s",
                        (self._tenant_id, intervention["id"]),
                    )
                raise DecisionConflict("proposal_generation_failed") from None
        else:
            generated = self._models.generate(self._tenant_id, context)
        record_usage(self._database_url, self._tenant_id, run["id"], generated.usage)
        output = generated.output
        policy = self._policy.evaluate(
            output.recommended_action,
            self._provider.capabilities(),
            **({"human_review": True} if phase7 else {}),
        )
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            # Model latency must not keep permission granted after membership/owner changes.
            self._authorize_request(connection, opportunity_id, actor_id)
            if phase7:
                current = connection.execute(
                    "select o.version,r.recommendations_enabled from public.ares_opportunities o join public.commercial_routines r on r.tenant_id=o.tenant_id where o.tenant_id=%s and o.id=%s for share of o,r",
                    (self._tenant_id, opportunity_id),
                ).fetchone()
                if (
                    not current
                    or not current["recommendations_enabled"]
                    or current["version"] != context["expected_opportunity_version"]
                    or decision_fingerprint_on(connection, self._tenant_id, opportunity_id)
                    != context["decision_fingerprint"]
                ):
                    connection.execute(
                        "update public.ares_interventions set status='cancelled',closed_at=now() where tenant_id=%s and id=%s",
                        (self._tenant_id, intervention["id"]),
                    )
                    connection.commit()
                    raise DecisionConflict("recommendation_context_stale")
            if analysis.get("state") == "ready":
                current = analysis_on(connection, self._tenant_id, UUID(actor_id), opportunity_id)
                if (
                    current.get("state") != "ready"
                    or current.get("workflow_id") != analysis["workflow_id"]
                    or current.get("source_fingerprint") != analysis["source_fingerprint"]
                ):
                    connection.execute(
                        "update public.agent_runs set status='failed',error_code='recommendation_analysis_stale',finished_at=now() where tenant_id=%s and id=%s",
                        (self._tenant_id, run["id"]),
                    )
                    connection.execute(
                        "update public.ares_interventions set status='cancelled',closed_at=now() where tenant_id=%s and id=%s",
                        (self._tenant_id, intervention["id"]),
                    )
                    connection.commit()
                    raise DecisionConflict("recommendation_analysis_stale")
            rec = connection.execute(
                """
                insert into public.recommendations (
                  tenant_id, intervention_id, opportunity_id, correlation_id, kind,
                  recommended_action, rationale, confidence, status, source, source_ref,
                  expires_at, context_ref, run_id, alternatives, contraindication,
                  output_schema_version, urgency, generation_mode
                ) values (%s, %s, %s, %s, 'next_best_action', %s, %s, %s, 'pending',
                  'ares', 'follow-up-agent:m3.1', now() + interval '24 hours', %s, %s,
                  %s, %s, 'recommendation.v1', %s, %s)
                returning id, version
                """,
                (
                    self._tenant_id,
                    intervention["id"],
                    opportunity_id,
                    correlation_id,
                    Jsonb(output.recommended_action.model_dump(mode="json")),
                    output.rationale,
                    output.confidence,
                    row["context_ref"],
                    run["id"],
                    Jsonb([item.model_dump(mode="json") for item in output.alternatives]),
                    output.contraindication,
                    output.triage.urgency,
                    generated.generation_mode,
                ),
            ).fetchone()
            assert rec is not None
            if phase7:
                connection.execute(
                    "insert into public.recommendation_context_guards(tenant_id,recommendation_id,opportunity_id,relevant_hash,expected_version,valid_until,plan_json) values(%s,%s,%s,%s,%s,now()+make_interval(hours=>%s),%s)",
                    (
                        self._tenant_id,
                        rec["id"],
                        opportunity_id,
                        context["decision_fingerprint"],
                        context["expected_opportunity_version"],
                        context["proposal_plan"]["valid_for_hours"],
                        Jsonb(context["proposal_plan"]),
                    ),
                )
                connection.execute(
                    "update public.recommendations set expires_at=now()+make_interval(hours=>%s) where tenant_id=%s and id=%s",
                    (context["proposal_plan"]["valid_for_hours"], self._tenant_id, rec["id"]),
                )
            connection.execute(
                "update public.recommendations set output_schema_version=%s where tenant_id=%s and id=%s",
                (generated.output_schema_version, self._tenant_id, rec["id"]),
            )
            if context.get("validated_triage") and not phase7:
                connection.execute(
                    "update public.agent_runs set agent_name='follow-up',agent_version='follow-up.v2',output_schema_version='recommendation.v2' where tenant_id=%s and id=%s",
                    (self._tenant_id, run["id"]),
                )
            connection.execute(
                "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'user',%s,'recommendation.analysis_source',%s,'ares',%s)",
                (
                    self._tenant_id,
                    actor_id,
                    correlation_id,
                    Jsonb(
                        {
                            "recommendation_id": str(rec["id"]),
                            "mode": "independent_triage"
                            if context.get("validated_triage")
                            else "legacy_fallback",
                            "analysis_state": analysis.get("state", "unavailable"),
                            "workflow_id": analysis.get("workflow_id"),
                        }
                    ),
                ),
            )
            response_version = int(rec["version"])
            validity_hours = context["proposal_plan"]["valid_for_hours"] if phase7 else 24
            policy_row = connection.execute(
                """
                insert into public.policy_decisions (
                  tenant_id, policy_set, policy_version, inputs_hash, verdict,
                  rules_matched, obligations, expires_at, intervention_id,
                  recommendation_id, action_kind, policy_hash, source, source_ref
                ) values (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(hours=>%s),
                  %s, %s, %s, %s, 'ares', 'policy:m3_actions.v1') returning id
                """,
                (
                    self._tenant_id,
                    policy.policy_set,
                    policy.policy_version,
                    generated.prompt_hash,
                    policy.verdict,
                    Jsonb(policy.rules_matched),
                    Jsonb(policy.obligations),
                    validity_hours,
                    intervention["id"],
                    rec["id"],
                    output.recommended_action.action_kind,
                    policy.policy_hash,
                ),
            ).fetchone()
            assert policy_row is not None
            if policy.verdict == "require_approval":
                connection.execute(
                    """
                    insert into public.approval_requests (
                      tenant_id, intervention_id, recommendation_id, policy_decision_id,
                      opportunity_id, correlation_id, required_role, expires_at
                    ) values (%s, %s, %s, %s, %s, %s, %s::public.membership_role,
                      now() + make_interval(hours=>%s))
                    """,
                    (
                        self._tenant_id,
                        intervention["id"],
                        rec["id"],
                        policy_row["id"],
                        opportunity_id,
                        correlation_id,
                        policy.required_role or "manager",
                        validity_hours,
                    ),
                )
            elif policy.verdict == "allow":
                decision = connection.execute(
                    """
                    insert into public.decisions (
                      tenant_id, intervention_id, recommendation_id, policy_decision_id,
                      correlation_id, actor_type, actor_id, verdict, reason, source,
                      source_ref, expected_version
                    ) values (%s, %s, %s, %s, %s, 'ares_agent', 'policy-engine:m3.1',
                      'approved', 'Ação de baixo risco autorizada pela Policy', 'ares',
                      'policy:m3_actions.v1', %s) returning id
                    """,
                    (
                        self._tenant_id,
                        intervention["id"],
                        rec["id"],
                        policy_row["id"],
                        correlation_id,
                        rec["version"],
                    ),
                ).fetchone()
                assert decision is not None
                updated = connection.execute(
                    """
                    update public.recommendations set status = 'approved', version = version + 1,
                      updated_at = now() where tenant_id = %s and id = %s returning version
                    """,
                    (self._tenant_id, rec["id"]),
                ).fetchone()
                assert updated is not None
                response_version = int(updated["version"])
                intent = connection.execute(
                    """
                    insert into public.action_intents (
                      tenant_id, intervention_id, recommendation_id, decision_id,
                      policy_decision_id, context_ref, correlation_id, action_kind,
                      action_payload, idempotency_key, actor_type, actor_id, source, source_ref
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      'ares_agent', 'policy-engine:m3.1', 'ares', 'policy:m3_actions.v1')
                    returning id
                    """,
                    (
                        self._tenant_id,
                        intervention["id"],
                        rec["id"],
                        decision["id"],
                        policy_row["id"],
                        row["context_ref"],
                        correlation_id,
                        output.recommended_action.action_kind,
                        Jsonb(output.recommended_action.payload),
                        f"recommendation:{rec['id']}:v{rec['version']}",
                    ),
                ).fetchone()
                assert intent is not None
                auto_intent_id = intent["id"]
                connection.execute(
                    """
                    insert into public.jobs (tenant_id, kind, payload, correlation_id)
                    values (%s, 'action.execute', %s, %s)
                    """,
                    (
                        self._tenant_id,
                        Jsonb({"intent_id": str(auto_intent_id)}),
                        correlation_id,
                    ),
                )
                self._transition(
                    connection,
                    opportunity_id,
                    "awaiting_decision",
                    "authorized",
                    "policy_allow_low_risk",
                    correlation_id,
                    "ares_agent",
                    "policy-engine:m3.1",
                )
                connection.execute(
                    """
                    update public.ares_opportunities set state = 'authorized',
                      version = version + 1, updated_at = now()
                    where tenant_id = %s and id = %s and state = 'awaiting_decision'
                    """,
                    (self._tenant_id, opportunity_id),
                )
                connection.execute(
                    """
                    update public.ares_interventions set status = 'executing'
                    where tenant_id = %s and id = %s
                    """,
                    (self._tenant_id, intervention["id"]),
                )
            elif policy.verdict == "deny":
                connection.execute(
                    """
                    update public.recommendations set status = 'rejected', version = version + 1,
                      updated_at = now() where tenant_id = %s and id = %s
                    """,
                    (self._tenant_id, rec["id"]),
                )
                connection.execute(
                    """update public.ares_interventions
                       set status = 'cancelled', closed_at = now()
                       where tenant_id = %s and id = %s""",
                    (self._tenant_id, intervention["id"]),
                )
            connection.execute(
                """
                update public.agent_runs set model_id = %s, prompt_hash = %s,
                  generation_mode = %s, status = %s, output_json = %s, error_code = %s,
                  finished_at = now() where tenant_id = %s and id = %s
                """,
                (
                    generated.model_id,
                    generated.prompt_hash,
                    generated.generation_mode,
                    generated.status,
                    Jsonb(
                        {
                            **output.model_dump(mode="json"),
                            "schema_version": generated.output_schema_version,
                            "analysis_source": {
                                "mode": "independent_triage"
                                if context.get("validated_triage")
                                else "legacy_fallback",
                                "state": analysis.get("state"),
                                "workflow_id": analysis.get("workflow_id"),
                                "source_fingerprint": analysis.get("source_fingerprint"),
                            },
                        }
                    ),
                    generated.error_code,
                    self._tenant_id,
                    run["id"],
                ),
            )
        return {
            "run_id": run["id"],
            "recommendation_id": rec["id"],
            "intervention_id": intervention["id"],
            "correlation_id": correlation_id,
            "status": "awaiting_approval"
            if policy.verdict == "require_approval"
            else "authorized"
            if policy.verdict == "allow"
            else policy.verdict,
            "version": response_version,
            "intent_id": auto_intent_id,
        }

    async def decide(
        self, recommendation_id: UUID, command: DecideCommand, actor_id: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.decide_sync, recommendation_id, command, actor_id)

    def decide_sync(
        self, recommendation_id: UUID, command: DecideCommand, actor_id: str
    ) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            self._require_contract(connection)
            actor_role = self._actor_role(connection, actor_id, lock=True)
            if actor_role not in {"admin", "manager", "seller"}:
                raise DecisionAuthorizationError()
            row = connection.execute(
                """
                select r.*, p.id as policy_decision_id, p.verdict as policy_verdict,
                  a.id as approval_id, a.status as approval_status, a.expires_at as approval_expires_at,
                  a.required_role::text as approval_required_role, o.owner_user_id
                from public.recommendations r
                join public.policy_decisions p on p.tenant_id = r.tenant_id
                  and p.recommendation_id = r.id
                left join public.approval_requests a on a.tenant_id = r.tenant_id
                  and a.recommendation_id = r.id
                join public.ares_opportunities o on o.tenant_id = r.tenant_id
                  and o.id = r.opportunity_id
                where r.tenant_id = %s and r.id = %s
                for update of r
                """,
                (self._tenant_id, recommendation_id),
            ).fetchone()
            if row is None:
                raise ValueError("recommendation_not_found")
            self._authorize_decision(actor_role, actor_id, row)
            if command.verdict != "rejected":
                guard_on(connection, self._tenant_id, recommendation_id)
            if int(row["version"]) != command.expected_version:
                raise DecisionConflict("stale_recommendation", int(row["version"]))
            if row["status"] != "pending" or row["approval_status"] != "pending":
                raise DecisionConflict("recommendation_already_decided", int(row["version"]))
            if row["approval_expires_at"] <= datetime.now(UTC):
                connection.execute(
                    """
                    update public.approval_requests set status = 'expired', updated_at = now()
                    where tenant_id = %s and id = %s
                    """,
                    (self._tenant_id, row["approval_id"]),
                )
                raise DecisionConflict("approval_expired", int(row["version"]))
            action = (
                command.edited_payload
                if command.verdict == "edited"
                else ActionDraft.model_validate(row["recommended_action"])
            )
            assert action is not None
            policy = self._policy.evaluate(
                action,
                self._provider.capabilities(),
                **(
                    {"human_review": True}
                    if row.get("output_schema_version") == "recommendation.v3"
                    else {}
                ),
            )
            if (
                command.verdict != "rejected"
                and policy.verdict == "require_approval"
                and not role_can_decide(actor_role, policy.required_role)
            ):
                raise DecisionAuthorizationError("approval_role_required")
            if command.verdict != "rejected" and policy.verdict == "deny":
                raise DecisionConflict("action_denied_by_policy", int(row["version"]))
            decision = connection.execute(
                """
                insert into public.decisions (
                  tenant_id, intervention_id, recommendation_id, policy_decision_id,
                  correlation_id, actor_type, actor_id, verdict, reason, source,
                  source_ref, edited_payload, expected_version
                ) values (%s, %s, %s, %s, %s, 'human', %s, %s, %s, 'human',
                  'approval-queue:m3', %s, %s) returning id
                """,
                (
                    self._tenant_id,
                    row["intervention_id"],
                    recommendation_id,
                    row["policy_decision_id"],
                    row["correlation_id"],
                    actor_id,
                    command.verdict,
                    command.reason,
                    Jsonb(command.edited_payload.model_dump(mode="json"))
                    if command.edited_payload
                    else None,
                    command.expected_version,
                ),
            ).fetchone()
            assert decision is not None
            new_status = "rejected" if command.verdict == "rejected" else "approved"
            connection.execute(
                """
                update public.recommendations set status = %s, version = version + 1,
                  updated_at = now() where tenant_id = %s and id = %s
                """,
                (new_status, self._tenant_id, recommendation_id),
            )
            connection.execute(
                """
                update public.approval_requests set status = %s, version = version + 1,
                  resolved_at = now(), resolved_by = %s, updated_at = now()
                  where tenant_id = %s and id = %s
                """,
                (
                    command.verdict,
                    actor_id,
                    self._tenant_id,
                    row["approval_id"],
                ),
            )
            if command.verdict == "rejected":
                connection.execute(
                    """
                    update public.ares_interventions set status = 'cancelled', closed_at = now()
                    where tenant_id = %s and id = %s
                    """,
                    (self._tenant_id, row["intervention_id"]),
                )
                return {"decision_id": decision["id"], "intent_id": None, "status": "rejected"}
            intent_key = f"recommendation:{recommendation_id}:v{command.expected_version}"
            intent = connection.execute(
                """
                insert into public.action_intents (
                  tenant_id, intervention_id, recommendation_id, decision_id,
                  policy_decision_id, context_ref, correlation_id, action_kind,
                  action_payload, idempotency_key, actor_type, actor_id, source, source_ref
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  'human', %s, 'human', 'approval-queue:m3') returning id
                """,
                (
                    self._tenant_id,
                    row["intervention_id"],
                    recommendation_id,
                    decision["id"],
                    row["policy_decision_id"],
                    row["context_ref"],
                    row["correlation_id"],
                    action.action_kind,
                    Jsonb(action.payload),
                    intent_key,
                    actor_id,
                ),
            ).fetchone()
            assert intent is not None
            connection.execute(
                """
                insert into public.jobs (tenant_id, kind, payload, correlation_id)
                values (%s, 'action.execute', %s, %s)
                """,
                (self._tenant_id, Jsonb({"intent_id": str(intent["id"])}), row["correlation_id"]),
            )
            self._transition(
                connection,
                row["opportunity_id"],
                "awaiting_decision",
                "authorized",
                "human_approval",
                row["correlation_id"],
                "human",
                actor_id,
            )
            connection.execute(
                """
                update public.ares_opportunities set state = 'authorized',
                  version = version + 1, updated_at = now()
                where tenant_id = %s and id = %s and state = 'awaiting_decision'
                """,
                (self._tenant_id, row["opportunity_id"]),
            )
            connection.execute(
                """update public.ares_interventions set status = 'executing'
                   where tenant_id = %s and id = %s""",
                (self._tenant_id, row["intervention_id"]),
            )
            connection.execute(
                "update public.recommendation_context_guards g set expected_version=o.version from public.ares_opportunities o where g.tenant_id=%s and g.recommendation_id=%s and o.tenant_id=g.tenant_id and o.id=g.opportunity_id",
                (self._tenant_id, recommendation_id),
            )
            return {
                "decision_id": decision["id"],
                "intent_id": intent["id"],
                "status": "authorized",
            }

    def execute_intent_sync(self, intent_id: UUID) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            intent = connection.execute(
                """
                select i.*, c.facts_json, o.state as opportunity_state,
                  x.opportunity_id, r.output_schema_version
                from public.action_intents i
                join public.recommendations r on r.tenant_id=i.tenant_id and r.id=i.recommendation_id
                join public.context_snapshots c on c.tenant_id = i.tenant_id and c.id = i.context_ref
                join public.ares_interventions x on x.tenant_id = i.tenant_id and x.id = i.intervention_id
                join public.ares_opportunities o on o.tenant_id = x.tenant_id and o.id = x.opportunity_id
                where i.tenant_id = %s and i.id = %s for update of i, o
                """,
                (self._tenant_id, intent_id),
            ).fetchone()
            if intent is None:
                raise ValueError("action_intent_not_found")
            if intent["status"] == "succeeded":
                return {"intent_id": intent_id, "status": "succeeded", "duplicate": True}
            if intent["status"] == "cancelled":
                return {"intent_id": intent_id, "status": "cancelled", "duplicate": True}
            guard_on(connection, self._tenant_id, intent["recommendation_id"])
            facts = intent["facts_json"]
            deal_facts = facts.get("deal", {})
            if isinstance(self._provider, TenantCRMProvider):
                target_connection = deal_facts.get("connection_id")
                self._provider.connection_id = (
                    UUID(str(target_connection)) if target_connection else None
                )
            deal_id = str(
                (deal_facts.get("external_ref") or {}).get("id")
                or deal_facts.get("external_id")
                or ""
            )
            if not deal_id:
                raise ValueError("opaque_target_not_resolvable")
            attempt_number_row = connection.execute(
                """select coalesce(max(attempt_no), 0) + 1 as next_attempt
                   from public.action_attempts
                   where tenant_id = %s and intent_id = %s""",
                (self._tenant_id, intent_id),
            ).fetchone()
            assert attempt_number_row is not None
            attempt_no = int(attempt_number_row["next_attempt"])
            attempt = connection.execute(
                """
                insert into public.action_attempts (
                  tenant_id, intent_id, intervention_id, correlation_id, attempt_no,
                  status, external_request, actor_id
                ) values (%s, %s, %s, %s, %s, 'running', %s, 'tick-worker:m3.1')
                returning id
                """,
                (
                    self._tenant_id,
                    intent_id,
                    intent["intervention_id"],
                    intent["correlation_id"],
                    attempt_no,
                    Jsonb({"action_kind": intent["action_kind"], "target_source": "context_ref"}),
                ),
            ).fetchone()
            assert attempt is not None
            connection.execute(
                """
                update public.action_intents set status = 'executing', started_at = coalesce(started_at, now()),
                  updated_at = now() where tenant_id = %s and id = %s
                """,
                (self._tenant_id, intent_id),
            )
            if intent["opportunity_state"] == "authorized":
                self._transition(
                    connection,
                    intent["opportunity_id"],
                    "authorized",
                    "executing",
                    "worker_claimed_action",
                    intent["correlation_id"],
                    "system",
                    "tick-worker:m3.1",
                )
                connection.execute(
                    """update public.ares_opportunities set state = 'executing', version = version + 1,
                       updated_at = now() where tenant_id = %s and id = %s""",
                    (self._tenant_id, intent["opportunity_id"]),
                )
            connection.execute(
                "update public.recommendation_context_guards g set expected_version=o.version from public.ares_opportunities o where g.tenant_id=%s and g.recommendation_id=%s and o.tenant_id=g.tenant_id and o.id=g.opportunity_id",
                (self._tenant_id, intent["recommendation_id"]),
            )
        payload = intent["action_payload"]
        if isinstance(self._provider, TenantCRMProvider):
            self._provider.correlation_id = str(intent["correlation_id"])
        try:
            with execution_contract(self._database_url, self._tenant_id) as authorization:
                try:
                    guard_on(authorization, self._tenant_id, intent["recommendation_id"])
                except DecisionConflict as error:
                    raise ExecutionBlocked(error.code) from error
                policy = self._policy.evaluate(
                    ActionDraft(action_kind=intent["action_kind"], payload=payload),
                    self._provider.capabilities(),
                    **(
                        {"human_review": True}
                        if intent.get("output_schema_version") == "recommendation.v3"
                        else {}
                    ),
                )
                if policy.verdict == "deny":
                    raise ExecutionBlocked("current_policy_denied")
                if intent["actor_type"] == "human":
                    role = self._actor_role(authorization, intent["actor_id"], lock=True)
                    if role not in {"admin", "manager", "seller"}:
                        raise ExecutionBlocked("decision_actor_forbidden")
                    if policy.verdict == "require_approval" and not role_can_decide(
                        role, policy.required_role
                    ):
                        raise ExecutionBlocked("approval_role_required")
                    if role == "seller":
                        owner = authorization.execute(
                            "select owner_user_id from public.ares_opportunities "
                            "where tenant_id=%s and id=%s for share",
                            (self._tenant_id, intent["opportunity_id"]),
                        ).fetchone()
                        if not owner or str(owner["owner_user_id"]) != intent["actor_id"]:
                            raise ExecutionBlocked("opportunity_scope_forbidden")
                elif policy.verdict != "allow":
                    raise ExecutionBlocked("approval_role_required")
                if intent["action_kind"] == "create_task":
                    result = self._provider.create_task(
                        deal_id, str(payload["title"]), intent["idempotency_key"]
                    )
                elif intent["action_kind"] == "add_note":
                    result = self._provider.add_note(
                        deal_id, str(payload["body"]), intent["idempotency_key"]
                    )
                else:
                    result = self._provider.update_deal_stage(
                        deal_id, str(payload["stage"]), intent["idempotency_key"]
                    )
        except ExecutionBlocked as error:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "update public.action_attempts set status='failed',error_code=%s,finished_at=now() "
                    "where tenant_id=%s and id=%s",
                    (error.code, self._tenant_id, attempt["id"]),
                )
                connection.execute(
                    "update public.action_intents set status='cancelled',finished_at=now(),updated_at=now() "
                    "where tenant_id=%s and id=%s",
                    (self._tenant_id, intent_id),
                )
                connection.execute(
                    "update public.ares_interventions set status='cancelled',closed_at=now() "
                    "where tenant_id=%s and id=%s",
                    (self._tenant_id, intent["intervention_id"]),
                )
                self._transition(
                    connection,
                    intent["opportunity_id"],
                    "executing",
                    "closed",
                    f"action_execution_blocked:{error.code}",
                    intent["correlation_id"],
                    "system",
                    "tick-worker:m3.1",
                )
                connection.execute(
                    "update public.ares_opportunities set state='closed',closed_at=now(),version=version+1,updated_at=now() "
                    "where tenant_id=%s and id=%s",
                    (self._tenant_id, intent["opportunity_id"]),
                )
            raise
        except Exception as error:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                    update public.action_attempts set status = 'failed', error_code = %s,
                      finished_at = now() where tenant_id = %s and id = %s
                    """,
                    (type(error).__name__[:80], self._tenant_id, attempt["id"]),
                )
                connection.execute(
                    """update public.action_intents set status = 'failed', updated_at = now()
                       where tenant_id = %s and id = %s""",
                    (self._tenant_id, intent_id),
                )
            raise
        response = result.model_dump(mode="json")
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            execution = connection.execute(
                """
                insert into public.action_executions (
                  tenant_id, intervention_id, correlation_id, executed_action, target,
                  actor_type, actor_id, source, source_ref, status, idempotency_key,
                  attempts, started_at, finished_at, result, intent_id, attempt_id,
                  recommendation_id, decision_id
                ) values (%s, %s, %s, %s, %s, 'system', 'tick-worker:m3.1', 'ares',
                  'fake-crm', 'succeeded', %s, %s, now(), now(), %s, %s, %s, %s, %s)
                on conflict (tenant_id, idempotency_key) do update
                  set result = excluded.result, finished_at = excluded.finished_at
                returning id
                """,
                (
                    self._tenant_id,
                    intent["intervention_id"],
                    intent["correlation_id"],
                    Jsonb({"action_kind": intent["action_kind"], "payload": payload}),
                    Jsonb(
                        {
                            "provider": "fake-crm",
                            "external_id": deal_id,
                            "resolved_from": str(intent["context_ref"]),
                        }
                    ),
                    intent["idempotency_key"],
                    attempt_no,
                    Jsonb(response),
                    intent_id,
                    attempt["id"],
                    intent["recommendation_id"],
                    intent["decision_id"],
                ),
            ).fetchone()
            assert execution is not None
            connection.execute(
                """
                update public.action_attempts set status = 'succeeded', external_response = %s,
                  finished_at = now() where tenant_id = %s and id = %s
                """,
                (Jsonb(response), self._tenant_id, attempt["id"]),
            )
            connection.execute(
                """
                update public.action_intents set status = 'succeeded', finished_at = now(),
                  updated_at = now() where tenant_id = %s and id = %s
                """,
                (self._tenant_id, intent_id),
            )
            state_after_ref = self._capture_state_after(
                connection, intent, execution["id"], response
            )
            connection.execute(
                """
                insert into public.outcomes (
                  tenant_id, intervention_id, opportunity_id, action_execution_id,
                  correlation_id, state_after_ref, result_type, attribution_level,
                  actor_type, actor_id, source, source_ref, observed_at
                ) values (%s, %s, %s, %s, %s, %s, 'action_executed', 'observed',
                  'system', 'tick-worker:m3.1', 'ares', 'fake-crm-response', now())
                """,
                (
                    self._tenant_id,
                    intent["intervention_id"],
                    intent["opportunity_id"],
                    execution["id"],
                    intent["correlation_id"],
                    state_after_ref,
                ),
            )
            self._transition(
                connection,
                intent["opportunity_id"],
                "executing",
                "observing",
                "crm_action_succeeded",
                intent["correlation_id"],
                "system",
                "tick-worker:m3.1",
            )
            connection.execute(
                """
                update public.ares_opportunities set state = 'observing', version = version + 1,
                  updated_at = now() where tenant_id = %s and id = %s
                """,
                (self._tenant_id, intent["opportunity_id"]),
            )
            connection.execute(
                """
                update public.ares_interventions set status = 'closed', state_after_ref = %s,
                  closed_at = now() where tenant_id = %s and id = %s
                """,
                (state_after_ref, self._tenant_id, intent["intervention_id"]),
            )
        return {"intent_id": intent_id, "status": "succeeded", "duplicate": result.duplicate}

    async def get_recommendation(
        self, recommendation_id: UUID, actor_id: str | None = None
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_recommendation_sync, recommendation_id, actor_id)

    async def get_latest_for_opportunity(
        self, opportunity_id: UUID, actor_id: str | None = None
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._get_latest_for_opportunity_sync, opportunity_id, actor_id
        )

    def _get_latest_for_opportunity_sync(
        self, opportunity_id: UUID, actor_id: str | None = None
    ) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """select id from public.recommendations
                   where tenant_id = %s and opportunity_id = %s
                   order by created_at desc limit 1""",
                (self._tenant_id, opportunity_id),
            ).fetchone()
        return self._get_recommendation_sync(row["id"], actor_id) if row else None

    def _get_recommendation_sync(
        self, recommendation_id: UUID, actor_id: str | None = None
    ) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                select r.*, p.verdict as policy_verdict, p.rules_matched, p.obligations,
                  p.policy_set, p.policy_version, p.policy_hash,
                  a.id as approval_id, a.status as approval_status,
                  a.expires_at as approval_expires_at,
                  a.required_role::text as approval_required_role, o.owner_user_id,
                  i.id as intent_id, i.status as action_status,
                  e.executed_action, e.result as execution_result, g.plan_json as proposal_plan, g.valid_until as proposal_valid_until
                from public.recommendations r
                join public.policy_decisions p on p.tenant_id = r.tenant_id and p.recommendation_id = r.id
                left join public.approval_requests a on a.tenant_id = r.tenant_id
                  and a.recommendation_id = r.id
                join public.ares_opportunities o on o.tenant_id = r.tenant_id
                  and o.id = r.opportunity_id
                left join public.recommendation_context_guards g on g.tenant_id=r.tenant_id and g.recommendation_id=r.id
                left join public.action_intents i on i.tenant_id = r.tenant_id
                  and i.recommendation_id = r.id
                left join public.action_executions e on e.tenant_id = i.tenant_id
                  and e.intent_id = i.id
                where r.tenant_id = %s and r.id = %s
                """,
                (self._tenant_id, recommendation_id),
            ).fetchone()
            role = self._actor_role(connection, actor_id) if row and actor_id else None
            reason = self._contract_block_reason(connection) if row else None
            if (
                row
                and row["status"] == "pending"
                and row["output_schema_version"] == "recommendation.v3"
            ):
                try:
                    guard_on(connection, self._tenant_id, row["id"])
                except DecisionConflict:
                    reason = "recommendation_context_stale"
        return self._decision_permissions(dict(row), role, actor_id, reason) if row else None

    async def list_approvals(self, actor_id: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._list_approvals_sync, actor_id)

    def _list_approvals_sync(self, actor_id: str | None = None) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                select r.id, a.id as approval_id, a.status, a.required_role,
                  a.required_role::text as approval_required_role, o.owner_user_id,
                  a.status as approval_status, a.expires_at as approval_expires_at,
                  a.version as approval_version, a.expires_at, a.created_at,
                  r.id as recommendation_id, r.version,
                  r.recommended_action, r.rationale, r.confidence, r.alternatives,
                  r.contraindication, r.urgency, r.generation_mode, r.context_ref,
                  r.output_schema_version, g.plan_json as proposal_plan, g.valid_until as proposal_valid_until,
                  r.intervention_id, r.correlation_id, p.verdict as policy_verdict,
                  o.id as opportunity_id, d.title, d.value as deal_value, d.currency
                from public.approval_requests a
                join public.recommendations r on r.tenant_id = a.tenant_id and r.id = a.recommendation_id
                join public.policy_decisions p on p.tenant_id = a.tenant_id and p.id = a.policy_decision_id
                join public.ares_opportunities o on o.tenant_id = a.tenant_id and o.id = a.opportunity_id
                join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id
                left join public.recommendation_context_guards g on g.tenant_id=r.tenant_id and g.recommendation_id=r.id
                where a.tenant_id = %s and a.status = 'pending'
                order by o.priority, a.expires_at, a.created_at
                """,
                (self._tenant_id,),
            ).fetchall()
            role = self._actor_role(connection, actor_id) if actor_id else None
            reason = self._contract_block_reason(connection)
            items = []
            for row in rows:
                blocked = reason
                if row["output_schema_version"] == "recommendation.v3" and blocked is None:
                    try:
                        guard_on(connection, self._tenant_id, row["recommendation_id"])
                    except DecisionConflict:
                        blocked = "recommendation_context_stale"
                items.append(self._decision_permissions(dict(row), role, actor_id, blocked))
        return {"items": items, "total": len(items)}

    async def get_action(self, intent_id: UUID) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_action_sync, intent_id)

    def _get_action_sync(self, intent_id: UUID) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            intent = connection.execute(
                "select * from public.action_intents where tenant_id = %s and id = %s",
                (self._tenant_id, intent_id),
            ).fetchone()
            if intent is None:
                return None
            attempts = connection.execute(
                """select * from public.action_attempts where tenant_id = %s and intent_id = %s
                   order by attempt_no""",
                (self._tenant_id, intent_id),
            ).fetchall()
            execution = connection.execute(
                """select * from public.action_executions where tenant_id = %s and intent_id = %s
                   order by created_at desc limit 1""",
                (self._tenant_id, intent_id),
            ).fetchone()
        return {
            "intent": dict(intent),
            "attempts": [dict(row) for row in attempts],
            "execution": dict(execution) if execution else None,
        }

    def _capture_state_after(
        self,
        connection: psycopg.Connection[Any],
        intent: dict[str, Any],
        execution_id: UUID,
        response: dict[str, Any],
    ) -> UUID:
        before = connection.execute(
            """select * from public.context_snapshots where tenant_id = %s and id = %s""",
            (self._tenant_id, intent["context_ref"]),
        ).fetchone()
        assert before is not None
        facts = dict(before["facts_json"])
        facts["latest_ares_execution"] = {
            "intervention_id": str(intent["intervention_id"]),
            "action_execution_id": str(execution_id),
            "result": response,
        }
        serialized = json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str)
        content_hash = hashlib.sha256(serialized.encode()).hexdigest()
        version_row = connection.execute(
            """select coalesce(max(snapshot_version), 0) + 1 as next_version
               from public.context_snapshots
               where tenant_id = %s and opportunity_id = %s""",
            (self._tenant_id, intent["opportunity_id"]),
        ).fetchone()
        assert version_row is not None
        version = version_row["next_version"]
        row = connection.execute(
            """
            insert into public.context_snapshots (
              tenant_id, opportunity_id, snapshot_version, opportunity_state, facts_json,
              citations_json, token_estimate, content_hash, source, source_ref, truncated,
              included_event_count, omitted_event_count, correlation_id
            ) values (%s, %s, %s, 'observing', %s, %s, %s, %s, 'ares',
              'decision-engine:m3.1', %s, %s, %s, %s) returning id
            """,
            (
                self._tenant_id,
                intent["opportunity_id"],
                version,
                Jsonb(facts),
                Jsonb(before["citations_json"]),
                before["token_estimate"],
                content_hash,
                before["truncated"],
                before["included_event_count"],
                before["omitted_event_count"],
                intent["correlation_id"],
            ),
        ).fetchone()
        assert row is not None
        return UUID(str(row["id"]))

    def _transition(
        self,
        connection: psycopg.Connection[Any],
        opportunity_id: UUID,
        from_state: str,
        to_state: str,
        reason: str,
        correlation_id: UUID,
        actor_type: str,
        actor_id: str,
    ) -> None:
        connection.execute(
            """
            insert into public.opportunity_state_transitions (
              tenant_id, opportunity_id, from_state, to_state, reason, correlation_id,
              actor_type, actor_id, source
            ) values (%s, %s, %s, %s, %s, %s, %s::public.actor_type, %s, 'ares')
            """,
            (
                self._tenant_id,
                opportunity_id,
                from_state,
                to_state,
                reason,
                correlation_id,
                actor_type,
                actor_id,
            ),
        )
