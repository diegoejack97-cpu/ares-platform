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

from ares.ai.budget import AIBudgetGuard
from ares.ai.usage import record_usage
from ares.connectors.provider import CRMProvider
from ares.decision.model_factory import RecommendationModelFactory
from ares.decision.models import ActionDraft, DecideCommand
from ares.decision.policy import PolicyEngine


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
        openai_model: str = "gpt-5-mini",
        estimated_cost_usd: Decimal = Decimal("0.01"),
    ) -> None:
        self._database_url = database_url
        self._tenant_id = tenant_id
        self._provider = provider
        self._policy = PolicyEngine()
        self._models = RecommendationModelFactory(
            api_key=openai_api_key,
            model_id=openai_model,
            budget_guard=AIBudgetGuard(database_url),
            estimated_cost_usd=estimated_cost_usd,
        )

    async def create_recommendation(self, opportunity_id: UUID) -> dict[str, Any]:
        return await asyncio.to_thread(self.create_recommendation_sync, opportunity_id)

    def create_recommendation_sync(self, opportunity_id: UUID) -> dict[str, Any]:
        correlation_id = uuid4()
        auto_intent_id: UUID | None = None
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
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
                return dict(existing)
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
            "opportunity": {
                "id": str(opportunity_id),
                "score": row["score"],
                "priority": row["priority"],
            },
            "context_ref": str(row["context_ref"]),
            "facts": row["facts_json"],
            "citations": row["citations_json"],
        }
        generated = self._models.generate(self._tenant_id, context)
        record_usage(self._database_url, self._tenant_id, run["id"], generated.usage)
        output = generated.output
        policy = self._policy.evaluate(output.recommended_action, self._provider.capabilities())
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
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
            response_version = int(rec["version"])
            policy_row = connection.execute(
                """
                insert into public.policy_decisions (
                  tenant_id, policy_set, policy_version, inputs_hash, verdict,
                  rules_matched, obligations, expires_at, intervention_id,
                  recommendation_id, action_kind, policy_hash, source, source_ref
                ) values (%s, %s, %s, %s, %s, %s, %s, now() + interval '24 hours',
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
                      now() + interval '24 hours')
                    """,
                    (
                        self._tenant_id,
                        intervention["id"],
                        rec["id"],
                        policy_row["id"],
                        opportunity_id,
                        correlation_id,
                        policy.required_role or "manager",
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
                    Jsonb(output.model_dump(mode="json")),
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
            row = connection.execute(
                """
                select r.*, p.id as policy_decision_id, p.verdict as policy_verdict,
                  a.id as approval_id, a.status as approval_status, a.expires_at as approval_expires_at
                from public.recommendations r
                join public.policy_decisions p on p.tenant_id = r.tenant_id
                  and p.recommendation_id = r.id
                left join public.approval_requests a on a.tenant_id = r.tenant_id
                  and a.recommendation_id = r.id
                where r.tenant_id = %s and r.id = %s
                for update of r
                """,
                (self._tenant_id, recommendation_id),
            ).fetchone()
            if row is None:
                raise ValueError("recommendation_not_found")
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
            policy = self._policy.evaluate(action, self._provider.capabilities())
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
                  x.opportunity_id
                from public.action_intents i
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
            facts = intent["facts_json"]
            deal_facts = facts.get("deal", {})
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
        payload = intent["action_payload"]
        try:
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

    async def get_recommendation(self, recommendation_id: UUID) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_recommendation_sync, recommendation_id)

    async def get_latest_for_opportunity(self, opportunity_id: UUID) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_latest_for_opportunity_sync, opportunity_id)

    def _get_latest_for_opportunity_sync(self, opportunity_id: UUID) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """select id from public.recommendations
                   where tenant_id = %s and opportunity_id = %s
                   order by created_at desc limit 1""",
                (self._tenant_id, opportunity_id),
            ).fetchone()
        return self._get_recommendation_sync(row["id"]) if row else None

    def _get_recommendation_sync(self, recommendation_id: UUID) -> dict[str, Any] | None:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                select r.*, p.verdict as policy_verdict, p.rules_matched, p.obligations,
                  p.policy_set, p.policy_version, p.policy_hash,
                  a.id as approval_id, a.status as approval_status,
                  a.expires_at as approval_expires_at,
                  i.id as intent_id, i.status as action_status,
                  e.executed_action, e.result as execution_result
                from public.recommendations r
                join public.policy_decisions p on p.tenant_id = r.tenant_id and p.recommendation_id = r.id
                left join public.approval_requests a on a.tenant_id = r.tenant_id
                  and a.recommendation_id = r.id
                left join public.action_intents i on i.tenant_id = r.tenant_id
                  and i.recommendation_id = r.id
                left join public.action_executions e on e.tenant_id = i.tenant_id
                  and e.intent_id = i.id
                where r.tenant_id = %s and r.id = %s
                """,
                (self._tenant_id, recommendation_id),
            ).fetchone()
        return dict(row) if row else None

    async def list_approvals(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._list_approvals_sync)

    def _list_approvals_sync(self) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                select r.id, a.id as approval_id, a.status, a.required_role,
                  a.version as approval_version, a.expires_at, a.created_at,
                  r.id as recommendation_id, r.version,
                  r.recommended_action, r.rationale, r.confidence, r.alternatives,
                  r.contraindication, r.urgency, r.generation_mode, r.context_ref,
                  r.intervention_id, r.correlation_id, p.verdict as policy_verdict,
                  o.id as opportunity_id, d.title, d.value as deal_value, d.currency
                from public.approval_requests a
                join public.recommendations r on r.tenant_id = a.tenant_id and r.id = a.recommendation_id
                join public.policy_decisions p on p.tenant_id = a.tenant_id and p.id = a.policy_decision_id
                join public.ares_opportunities o on o.tenant_id = a.tenant_id and o.id = a.opportunity_id
                join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id
                where a.tenant_id = %s and a.status = 'pending'
                order by o.priority, a.expires_at, a.created_at
                """,
                (self._tenant_id,),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": len(rows)}

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
        return row["id"]

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
