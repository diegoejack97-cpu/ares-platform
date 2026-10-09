"""Durable, fenced, tenant-scoped supervisor. Models never select targets or jobs."""
# SQL statements remain complete for review.
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.agents.analysis_reader import analysis_on
from ares.agents.catalog import (
    CATALOG,
    SPECIALIST_VERSION,
    VERSION,
    catalog_hash,
    digest,
    sequence,
    validate_step,
)
from ares.agents.contracts import (
    AgentJob,
    AnalysisInput,
    AnalysisOutput,
    RoutineCommand,
    StartAnalysis,
)
from ares.agents.executor import AgentExecutor, AgentOutcome, AgnoExecutor, InvalidAgentOutput
from ares.agents.specialists import (
    DiagnosisAnalysis,
    SpecialistInput,
    TriageAnalysis,
    validate_grounding,
)
from ares.ai.quotas import QuotaGuard, estimate_usd
from ares.ai.usage import UsageObservation, record_usage_on
from ares.auth.models import AuthenticatedUser
from ares.decision.execution_guard import ExecutionBlocked, check_execution_contract
from ares.intelligence.context_builder import (
    ContextBuilder,
    ContextUnavailable,
    encode,
    fingerprint,
)

ACTIVE = ("queued", "running")
ROUTINE = "context-analysis"


class AgentRuntimeError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code, self.status = code, status


class LeaseLost(Exception):
    pass


@dataclass(frozen=True)
class AgentAttemptReceipt:
    job_id: UUID
    succeeded: bool


class AgentRuntime:
    def __init__(
        self,
        database_url: str,
        *,
        model_id: str = "gpt-5.4",
        api_key: str = "",
        worker_name: str = "ares-agent",
        max_concurrent: int = 2,
        executor: AgentExecutor | None = None,
    ) -> None:
        if not 1 <= max_concurrent <= 16:
            raise ValueError("invalid_agent_concurrency")
        self.url, self.model_id, self.worker_name = database_url, model_id, worker_name
        self.max_concurrent = max_concurrent
        self.executor = executor or AgnoExecutor(api_key)

    def _db(self) -> psycopg.Connection[dict[str, Any]]:
        db = psycopg.connect(self.url, row_factory=dict_row)
        db.execute("set local statement_timeout='5s'")
        return db

    @staticmethod
    def _membership(db: psycopg.Connection[Any], tenant: UUID, actor: UUID) -> str:
        row = db.execute(
            "select m.role::text role from public.memberships m join public.tenants t on t.id=m.tenant_id where m.tenant_id=%s and m.user_id=%s and m.active and t.status='active' and exists(select 1 from public.tenant_entitlements e where e.tenant_id=m.tenant_id and e.module='ares_connect' and e.status='active' and (e.expires_at is null or e.expires_at>clock_timestamp())) for share of m,t",
            (tenant, actor),
        ).fetchone()
        if not row:
            raise AgentRuntimeError("agent_access_denied", 403)
        return str(row["role"])

    def _authorize(
        self,
        db: psycopg.Connection[Any],
        workflow: dict[str, Any],
        *,
        execute: bool = True,
    ) -> None:
        role = self._membership(db, workflow["tenant_id"], workflow["actor_id"])
        if execute and role == "auditor":
            raise AgentRuntimeError("agent_actor_read_only", 403)
        row = db.execute(
            "select owner_user_id from public.ares_opportunities where tenant_id=%s and id=%s for share",
            (workflow["tenant_id"], workflow["opportunity_id"]),
        ).fetchone()
        if not row or (role == "seller" and row["owner_user_id"] != workflow["actor_id"]):
            raise AgentRuntimeError("agent_scope_denied", 403)
        if execute:
            try:
                check_execution_contract(db, workflow["tenant_id"])
            except ExecutionBlocked as error:
                raise AgentRuntimeError(error.code, 403) from error
            routine = db.execute(
                "select enabled,specialists_enabled from public.agent_routines where tenant_id=%s and routine_id=%s for share",
                (workflow["tenant_id"], ROUTINE),
            ).fetchone()
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s for share",
                (workflow["tenant_id"],),
            ).fetchone()
            # Legacy follow-up+triage reserves the first routine slot, explicitly.
            if not routine or not routine["enabled"] or not quota or quota["agent_slots"] < 2:
                raise AgentRuntimeError("agent_routine_unavailable", 403)
            if (
                workflow.get("definition_version") == SPECIALIST_VERSION
                and not routine["specialists_enabled"]
            ):
                raise AgentRuntimeError("agent_specialists_disabled", 403)

    def routines(self, user: AuthenticatedUser) -> dict[str, Any]:
        with self._db() as db:
            role = self._membership(db, user.tenant_id, user.user_id)
            if role not in {"admin", "manager", "auditor"}:
                raise AgentRuntimeError("agent_access_denied", 403)
            row = db.execute(
                "select enabled,version,specialists_enabled from public.agent_routines where tenant_id=%s and routine_id=%s",
                (user.tenant_id, ROUTINE),
            ).fetchone()
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            slots = int(quota["agent_slots"]) if quota else 0
        return {
            "agent_slots": slots,
            "active_routines": 1 + int(bool(row and row["enabled"])),
            "items": [
                {
                    "routine_id": "follow-up-triage",
                    "enabled": True,
                    "available": slots >= 1,
                    "agents": ["follow-up+triage"],
                    "managed": "legacy",
                },
                {
                    "routine_id": ROUTINE,
                    "enabled": bool(row and row["enabled"]),
                    "available": bool(row and row["enabled"] and slots >= 2),
                    "version": row["version"] if row else 0,
                    "agents": list(
                        sequence(
                            SPECIALIST_VERSION if row and row["specialists_enabled"] else VERSION
                        )
                    ),
                    "specialists_enabled": bool(row and row["specialists_enabled"]),
                },
            ],
            "definitions": [
                {
                    "agent_id": item.agent_id,
                    "version": item.version,
                    "objective": item.objective,
                    "definition_hash": item.definition_hash,
                    "autonomy": item.autonomy,
                    "tools": item.tools,
                    "timeout_seconds": item.timeout_seconds,
                    "max_attempts": item.max_attempts,
                    "max_steps": item.max_steps,
                    "input_schema_version": item.input_schema_version,
                    "output_schema_version": item.output_schema_version,
                    "allowed_models": item.allowed_models,
                }
                for item in CATALOG.values()
            ],
        }

    def configure(self, user: AuthenticatedUser, command: RoutineCommand) -> dict[str, Any]:
        with self._db() as db:
            if self._membership(db, user.tenant_id, user.user_id) != "admin":
                raise AgentRuntimeError("agent_admin_required", 403)
            try:
                check_execution_contract(db, user.tenant_id)
            except ExecutionBlocked as error:
                raise AgentRuntimeError(error.code, 403) from error
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s for update",
                (user.tenant_id,),
            ).fetchone()
            if command.enabled and (not quota or quota["agent_slots"] < 2):
                raise AgentRuntimeError("agent_capacity_unavailable")
            row = db.execute(
                "select * from public.agent_routines where tenant_id=%s and routine_id=%s for update",
                (user.tenant_id, ROUTINE),
            ).fetchone()
            version = row["version"] if row else 0
            if version != command.expected_version:
                raise AgentRuntimeError("agent_routine_version_conflict")
            db.execute(
                "insert into public.agent_routines(tenant_id,routine_id,enabled,version,updated_by) values(%s,%s,%s,1,%s) on conflict(tenant_id,routine_id) do update set enabled=excluded.enabled,version=agent_routines.version+1,updated_by=excluded.updated_by,updated_at=now()",
                (user.tenant_id, ROUTINE, command.enabled, user.user_id),
            )
            self._audit(
                db,
                user.tenant_id,
                user.user_id,
                "agent_routine.configure",
                {
                    "routine": ROUTINE,
                    "enabled": command.enabled,
                    "previous_enabled": row["enabled"] if row else False,
                    "version": version + 1,
                    "reason": command.reason,
                },
            )
        return self.routines(user)

    def configure_specialists(
        self, user: AuthenticatedUser, command: RoutineCommand
    ) -> dict[str, Any]:
        with self._db() as db:
            if self._membership(db, user.tenant_id, user.user_id) != "admin":
                raise AgentRuntimeError("agent_admin_required", 403)
            try:
                check_execution_contract(db, user.tenant_id)
            except ExecutionBlocked as error:
                raise AgentRuntimeError(error.code, 403) from error
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s for update",
                (user.tenant_id,),
            ).fetchone()
            if command.enabled and (not quota or quota["agent_slots"] < 2):
                raise AgentRuntimeError("agent_capacity_unavailable")
            row = db.execute(
                "select * from public.agent_routines where tenant_id=%s and routine_id=%s for update",
                (user.tenant_id, ROUTINE),
            ).fetchone()
            if not row or not row["enabled"]:
                raise AgentRuntimeError("agent_routine_unavailable")
            if row["version"] != command.expected_version:
                raise AgentRuntimeError("agent_routine_version_conflict")
            db.execute(
                "update public.agent_routines set specialists_enabled=%s,version=version+1,updated_by=%s,updated_at=now() where tenant_id=%s and routine_id=%s",
                (command.enabled, user.user_id, user.tenant_id, ROUTINE),
            )
            self._audit(
                db,
                user.tenant_id,
                user.user_id,
                "agent_specialists.configure",
                {
                    "enabled": command.enabled,
                    "version": row["version"] + 1,
                    "reason": command.reason,
                },
            )
        return self.routines(user)

    def start(self, user: AuthenticatedUser, command: StartAnalysis) -> dict[str, Any]:
        request_hash = digest(command.model_dump(exclude={"idempotency_key"}))
        with self._db() as db:
            # Serialize admission/configuration for one tenant. No in-memory counter.
            db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s for update",
                (user.tenant_id,),
            )
            scope = {
                "tenant_id": user.tenant_id,
                "actor_id": user.user_id,
                "opportunity_id": command.opportunity_id,
            }
            self._authorize(db, scope)
            receipt = db.execute(
                "select w.*,r.request_hash as receipt_hash from public.agent_analysis_requests r join public.agent_workflows w on w.tenant_id=r.tenant_id and w.id=r.workflow_id where r.tenant_id=%s and r.actor_id=%s and r.idempotency_key=%s",
                (user.tenant_id, user.user_id, command.idempotency_key),
            ).fetchone()
            if receipt:
                if receipt["receipt_hash"] != request_hash:
                    raise AgentRuntimeError("agent_idempotency_conflict")
                return self._public(receipt)
            prior = db.execute(
                "select * from public.agent_workflows where tenant_id=%s and actor_id=%s and idempotency_key=%s",
                (user.tenant_id, user.user_id, command.idempotency_key),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise AgentRuntimeError("agent_idempotency_conflict")
                return self._public(prior)
            flag = db.execute(
                "select specialists_enabled from public.agent_routines where tenant_id=%s and routine_id=%s",
                (user.tenant_id, ROUTINE),
            ).fetchone()
            version = SPECIALIST_VERSION if flag and flag["specialists_enabled"] else VERSION
            steps = sequence(version)
            if self.model_id not in CATALOG[steps[0]].allowed_models:
                raise AgentRuntimeError("agent_model_unavailable", 503)
            snapshot = self._snapshot(
                db, user.tenant_id, command.opportunity_id, command.context_ref
            )
            source = (
                self._specialist_projection(db, scope, command.context_ref)
                if version == SPECIALIST_VERSION
                else None
            )
            payload = (
                self._input(snapshot, None)
                if source is None
                else SpecialistInput(
                    context_ref=command.context_ref,
                    content_hash=source["content_hash"],
                    content=source["content"],
                    evidence_refs=source["evidence_refs"],
                )
            )
            if source:
                reusable = db.execute(
                    "select * from public.agent_workflows where tenant_id=%s and actor_id=%s and opportunity_id=%s and definition_version=%s and source_fingerprint=%s and analysis_valid_until>clock_timestamp() and status in ('queued','running','succeeded') order by created_at desc limit 1",
                    (
                        user.tenant_id,
                        user.user_id,
                        command.opportunity_id,
                        version,
                        source["relevant_hash"],
                    ),
                ).fetchone()
                if reusable:
                    db.execute(
                        "insert into public.agent_analysis_requests(tenant_id,actor_id,idempotency_key,request_hash,workflow_id) values(%s,%s,%s,%s,%s)",
                        (
                            user.tenant_id,
                            user.user_id,
                            command.idempotency_key,
                            request_hash,
                            reusable["id"],
                        ),
                    )
                    return self._public(reusable)
            if len(payload.model_dump_json().encode()) > CATALOG[steps[0]].max_input_bytes:
                raise AgentRuntimeError("agent_input_too_large", 422)
            pending = db.execute(
                "select count(*) count from public.agent_workflows where tenant_id=%s and status in ('queued','running')",
                (user.tenant_id,),
            ).fetchone()
            if pending and pending["count"] >= 20:
                raise AgentRuntimeError("agent_queue_full", 429)
            workflow_id, correlation = uuid4(), uuid4()
            # Conservative per-step estimate also covers schemas/instructions.
            limit = estimate_usd(self.model_id, CATALOG[steps[0]].max_input_bytes) * len(steps)
            row = db.execute(
                "insert into public.agent_workflows(id,tenant_id,actor_id,opportunity_id,context_ref,routine_id,definition_version,definition_hash,model_id,purpose,idempotency_key,request_hash,correlation_id,max_steps,max_depth,budget_limit_usd,deadline_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,4,3,%s,now()+interval '5 minutes') returning *",
                (
                    workflow_id,
                    user.tenant_id,
                    user.user_id,
                    command.opportunity_id,
                    command.context_ref,
                    ROUTINE,
                    version,
                    catalog_hash(version),
                    self.model_id,
                    command.purpose,
                    command.idempotency_key,
                    request_hash,
                    correlation,
                    limit,
                ),
            ).fetchone()
            assert row
            if source:
                row = db.execute(
                    "update public.agent_workflows set source_fingerprint=%s,source_content_hash=%s,source_content_json=%s,analysis_valid_until=now()+interval '10 minutes' where tenant_id=%s and id=%s returning *",
                    (
                        source["relevant_hash"],
                        source["content_hash"],
                        Jsonb(json.loads(source["content"])),
                        user.tenant_id,
                        workflow_id,
                    ),
                ).fetchone()
                assert row
            self._enqueue(db, row, steps[0], 0, None)
            self._audit(
                db,
                user.tenant_id,
                user.user_id,
                "agent_workflow.created",
                {"workflow_id": str(workflow_id), "context_ref": str(command.context_ref)},
            )
            return self._public(row)

    def get(self, user: AuthenticatedUser, workflow_id: UUID) -> dict[str, Any]:
        with self._db() as db:
            workflow = self._owned(db, user, workflow_id)
            self._authorize(db, workflow, execute=False)
            runs = db.execute(
                "select id,parent_run_id,agent_name,agent_version,status,depth,checkpoint,output_json,error_code,started_at,finished_at,input_schema_version,output_schema_version from public.agent_runs where tenant_id=%s and workflow_id=%s order by started_at,id",
                (user.tenant_id, workflow_id),
            ).fetchall()
            handoffs = db.execute(
                "select from_run_id,to_job_id,to_agent,schema_version from public.agent_handoffs where tenant_id=%s and workflow_id=%s order by created_at,id",
                (user.tenant_id, workflow_id),
            ).fetchall()
            return {
                **self._public(workflow),
                "runs": [dict(row) for row in runs],
                "handoffs": [dict(row) for row in handoffs],
            }

    def analysis(self, user: AuthenticatedUser, opportunity: UUID) -> dict[str, Any]:
        with self._db() as db:
            scope = {
                "tenant_id": user.tenant_id,
                "actor_id": user.user_id,
                "opportunity_id": opportunity,
            }
            self._authorize(db, scope, execute=False)
            result = analysis_on(db, user.tenant_id, user.user_id, opportunity)
            try:
                self._authorize(db, scope)
                result["can_request"] = result["enabled"]
            except AgentRuntimeError:
                result["can_request"] = False
            return result

    def cancel(self, user: AuthenticatedUser, workflow_id: UUID) -> dict[str, Any]:
        with self._db() as db:
            workflow = self._owned(db, user, workflow_id, lock=True)
            self._authorize(db, workflow, execute=False)
            if workflow["status"] in ACTIVE:
                self._stop(db, workflow, "cancelled", "agent_cancelled")
                self._audit(
                    db,
                    user.tenant_id,
                    user.user_id,
                    "agent_workflow.cancelled",
                    {"workflow_id": str(workflow_id)},
                )
        return self.get(user, workflow_id)

    @staticmethod
    def _owned(
        db: psycopg.Connection[Any],
        user: AuthenticatedUser,
        workflow_id: UUID,
        *,
        lock: bool = False,
    ) -> dict[str, Any]:
        if lock:
            db.execute(
                "select 1 from public.tenant_quotas where tenant_id=%s for update",
                (user.tenant_id,),
            )
        row = db.execute(
            "select * from public.agent_workflows where tenant_id=%s and actor_id=%s and id=%s"
            + (" for update" if lock else ""),
            (user.tenant_id, user.user_id, workflow_id),
        ).fetchone()
        if not row:
            raise AgentRuntimeError("agent_workflow_not_found", 404)
        return dict(row)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "id",
                "correlation_id",
                "root_run_id",
                "status",
                "routine_id",
                "definition_version",
                "definition_hash",
                "purpose",
                "error_code",
                "created_at",
                "finished_at",
                "deadline_at",
                "max_steps",
                "max_depth",
                "budget_limit_usd",
                "analysis_valid_until",
                "source_fingerprint",
                "source_content_hash",
            )
        }

    @staticmethod
    def _snapshot(
        db: psycopg.Connection[Any], tenant: UUID, opportunity: UUID, context: UUID
    ) -> dict[str, Any]:
        row = ContextBuilder.legacy_snapshot_on(db, tenant, opportunity, context)
        if not row:
            raise AgentRuntimeError("agent_context_stale_or_missing")
        return dict(row)

    @staticmethod
    def _input(snapshot: dict[str, Any], previous: AnalysisOutput | None) -> AnalysisInput:
        projection = ContextBuilder.legacy_projection(snapshot)
        return AnalysisInput(
            context_ref=snapshot["id"],
            content_hash=projection["content_hash"],
            content=projection["content"],
            evidence_refs=[str(item["event_id"]) for item in projection["citations"]][:20],
            previous=previous,
        )

    @staticmethod
    def _specialist_projection(
        db: psycopg.Connection[Any], workflow: dict[str, Any], context: UUID | None = None
    ) -> dict[str, Any]:
        try:
            result = ContextBuilder.specialist_projection_on(
                db, workflow["tenant_id"], workflow["opportunity_id"], context
            )
        except ContextUnavailable as error:
            raise AgentRuntimeError(error.code, error.status) from error
        if workflow.get("source_fingerprint") and (
            result["relevant_hash"] != workflow["source_fingerprint"]
            or workflow["analysis_valid_until"] <= datetime.now(UTC)
        ):
            raise AgentRuntimeError("agent_analysis_stale")
        if workflow.get("source_content_json"):
            if fingerprint(workflow["source_content_json"]) != workflow["source_content_hash"]:
                raise AgentRuntimeError("agent_context_hash_invalid")
            result["content"] = encode(workflow["source_content_json"])
            result["content_hash"] = workflow["source_content_hash"]
        return result

    @staticmethod
    def _enqueue(
        db: psycopg.Connection[Any],
        workflow: dict[str, Any],
        agent: str,
        depth: int,
        parent: UUID | None,
    ) -> UUID:
        job_id = uuid4()
        payload = AgentJob.model_validate(
            {
                "workflow_id": workflow["id"],
                "agent_id": agent,
                "depth": depth,
                "parent_run_id": parent,
            }
        )
        db.execute(
            "insert into public.jobs(id,tenant_id,kind,payload,correlation_id) values(%s,%s,'agent.execute',%s,%s)",
            (
                job_id,
                workflow["tenant_id"],
                Jsonb(payload.model_dump(mode="json")),
                workflow["correlation_id"],
            ),
        )
        if parent:
            db.execute(
                "insert into public.agent_handoffs(tenant_id,workflow_id,from_run_id,to_job_id,to_agent,schema_version) values(%s,%s,%s,%s,%s,%s)",
                (
                    workflow["tenant_id"],
                    workflow["id"],
                    parent,
                    job_id,
                    agent,
                    "triage-output.v1"
                    if workflow["definition_version"] == SPECIALIST_VERSION
                    else "analysis-output.v1",
                ),
            )
        return job_id

    @staticmethod
    def _audit(
        db: psycopg.Connection[Any], tenant: UUID, actor: UUID, action: str, payload: dict[str, Any]
    ) -> None:
        # References and administrative reason only; no prompt, customer data or secret.
        db.execute(
            "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'user',%s,%s,%s,'ares',%s)",
            (tenant, actor, action, uuid4(), Jsonb(payload)),
        )

    @staticmethod
    def _stop(
        db: psycopg.Connection[Any], workflow: dict[str, Any], status: str, code: str
    ) -> None:
        db.execute(
            "update public.agent_workflows set status=%s,error_code=%s,finished_at=now() where tenant_id=%s and id=%s and status in ('queued','running')",
            (status, code, workflow["tenant_id"], workflow["id"]),
        )
        db.execute(
            "update public.jobs set status='failed',error_code=%s,finished_at=now(),updated_at=now(),lease_token=null,lease_owner=null,lease_until=null where tenant_id=%s and kind='agent.execute' and payload->>'workflow_id'=%s and status in ('queued','running')",
            (code, workflow["tenant_id"], str(workflow["id"])),
        )
        db.execute(
            "update public.agent_runs set status='failed',error_code=%s,finished_at=now() where tenant_id=%s and workflow_id=%s and status='running'",
            (code, workflow["tenant_id"], workflow["id"]),
        )
        # Only attempts known not to have been dispatched can release a reservation.
        prepared = db.execute(
            "select id from public.agent_runs where tenant_id=%s and workflow_id=%s and checkpoint='prepared'",
            (workflow["tenant_id"], workflow["id"]),
        ).fetchall()
        for row in prepared:
            record_usage_on(
                db, workflow["tenant_id"], row["id"], UsageObservation(status="not_called")
            )

    def recover(self) -> int:
        recovered = 0
        with self._db() as db:
            tenants = db.execute(
                "select q.tenant_id from public.tenant_quotas q where exists(select 1 from public.agent_workflows w where w.tenant_id=q.tenant_id and w.status in ('queued','running')) order by q.tenant_id for update skip locked limit 20"
            ).fetchall()
            if not tenants:
                return 0
            # Lock workflow before job, the same order as finish/cancel/claim.
            workflows = db.execute(
                "select * from public.agent_workflows w where tenant_id=any(%s) and status in ('queued','running') and (deadline_at<now() or exists(select 1 from public.jobs j where j.tenant_id=w.tenant_id and j.kind='agent.execute' and j.payload->>'workflow_id'=w.id::text and j.status='running' and j.lease_until<now())) order by created_at limit 20 for update skip locked",
                ([row["tenant_id"] for row in tenants],),
            ).fetchall()
            for workflow in workflows:
                if workflow["deadline_at"] <= datetime.now(UTC):
                    self._stop(db, workflow, "failed", "agent_chain_timeout")
                else:
                    jobs = db.execute(
                        "select * from public.jobs where tenant_id=%s and kind='agent.execute' and payload->>'workflow_id'=%s and status='running' and lease_until<now() for update",
                        (workflow["tenant_id"], str(workflow["id"])),
                    ).fetchall()
                    for job in jobs:
                        run = db.execute(
                            "select * from public.agent_runs where tenant_id=%s and workflow_id=%s and lease_token=%s",
                            (workflow["tenant_id"], workflow["id"], job["lease_token"]),
                        ).fetchone()
                        if run and run["checkpoint"] == "dispatched":
                            self._stop(db, workflow, "failed", "agent_model_result_unknown")
                        elif int(job["attempts"]) >= 2:
                            self._stop(db, workflow, "failed", "agent_attempts_exhausted")
                        else:
                            if run:
                                record_usage_on(
                                    db,
                                    workflow["tenant_id"],
                                    run["id"],
                                    UsageObservation(status="not_called"),
                                )
                                db.execute(
                                    "update public.agent_runs set status='failed',finished_at=now(),error_code='agent_lease_expired_before_dispatch' where id=%s and tenant_id=%s",
                                    (run["id"], workflow["tenant_id"]),
                                )
                            db.execute(
                                "update public.jobs set status='queued',lease_token=null,lease_owner=null,lease_until=null,updated_at=now() where id=%s and tenant_id=%s",
                                (job["id"], workflow["tenant_id"]),
                            )
                recovered += 1
        return recovered

    def _claim(self) -> dict[str, Any] | None:
        with self._db() as db:
            # Admission is serialized by a durable tenant lock, not just SKIP LOCKED.
            quotas = db.execute(
                "select q.tenant_id from public.tenant_quotas q where exists(select 1 from public.jobs j where j.tenant_id=q.tenant_id and j.kind='agent.execute' and j.status='queued' and j.run_after<=now()) order by q.tenant_id for update skip locked limit 20"
            ).fetchall()
            for quota in quotas:
                tenant = quota["tenant_id"]
                count = db.execute(
                    "select count(*) count from public.jobs where tenant_id=%s and kind='agent.execute' and status='running' and lease_until>=now()",
                    (tenant,),
                ).fetchone()
                if count and count["count"] >= self.max_concurrent:
                    continue
                workflow = db.execute(
                    "select w.* from public.agent_workflows w where w.tenant_id=%s and w.status in ('queued','running') and exists(select 1 from public.jobs j where j.tenant_id=w.tenant_id and j.kind='agent.execute' and j.payload->>'workflow_id'=w.id::text and j.status='queued' and j.run_after<=now()) order by w.created_at for update skip locked limit 1",
                    (tenant,),
                ).fetchone()
                if not workflow:
                    continue
                job = db.execute(
                    "select * from public.jobs where tenant_id=%s and kind='agent.execute' and payload->>'workflow_id'=%s and status='queued' and run_after<=now() order by created_at for update skip locked limit 1",
                    (tenant, str(workflow["id"])),
                ).fetchone()
                if not job:
                    continue
                token = uuid4()
                db.execute(
                    "update public.jobs set status='running',attempts=attempts+1,lease_owner=%s,lease_token=%s,lease_until=now()+interval '30 seconds',updated_at=now() where id=%s and tenant_id=%s",
                    (self.worker_name, token, job["id"], tenant),
                )
                db.execute(
                    "update public.agent_workflows set status='running' where tenant_id=%s and id=%s",
                    (tenant, workflow["id"]),
                )
                return {
                    **dict(job),
                    "lease_token": token,
                    "attempts": job["attempts"] + 1,
                    "workflow": dict(workflow),
                }
        return None

    def _fence(self, db: psycopg.Connection[Any], claimed: dict[str, Any]) -> dict[str, Any]:
        db.execute(
            "select 1 from public.tenant_quotas where tenant_id=%s for update",
            (claimed["tenant_id"],),
        )
        workflow = db.execute(
            "select * from public.agent_workflows where tenant_id=%s and id=%s for update",
            (claimed["tenant_id"], claimed["workflow"]["id"]),
        ).fetchone()
        job = db.execute(
            "select 1 from public.jobs where tenant_id=%s and id=%s and lease_token=%s and status='running' and lease_until>clock_timestamp() for update",
            (claimed["tenant_id"], claimed["id"], claimed["lease_token"]),
        ).fetchone()
        if not workflow or workflow["status"] not in ACTIVE or not job:
            raise LeaseLost
        return dict(workflow)

    def _prepare(self, claimed: dict[str, Any]) -> tuple[UUID, AnalysisInput | SpecialistInput]:
        with self._db() as db:
            workflow = self._fence(db, claimed)
            try:
                self._authorize(db, workflow)
                request = AgentJob.model_validate(claimed["payload"])
                steps = sequence(workflow["definition_version"])
                visited = db.execute(
                    "select distinct agent_name from public.agent_runs where tenant_id=%s and workflow_id=%s and status in ('succeeded','degraded')",
                    (workflow["tenant_id"], workflow["id"]),
                ).fetchall()
                definition = validate_step(
                    request.agent_id,
                    request.depth,
                    tuple(row["agent_name"] for row in visited),
                    workflow["definition_version"],
                )
                if (
                    request.workflow_id != workflow["id"]
                    or workflow["definition_hash"] != catalog_hash(workflow["definition_version"])
                    or workflow["model_id"] not in definition.allowed_models
                ):
                    raise AgentRuntimeError("agent_definition_unavailable")
                if (
                    request.depth > workflow["max_depth"]
                    or request.depth >= workflow["max_steps"]
                    or claimed["attempts"] > definition.max_attempts
                ):
                    raise AgentRuntimeError("agent_step_limit")
                if workflow["deadline_at"] <= datetime.now(UTC):
                    raise AgentRuntimeError("agent_chain_timeout")
                step_count = db.execute(
                    "select count(*) count from public.agent_runs where tenant_id=%s and workflow_id=%s",
                    (workflow["tenant_id"], workflow["id"]),
                ).fetchone()
                if step_count and step_count["count"] >= workflow["max_steps"]:
                    raise AgentRuntimeError("agent_step_limit")
                previous = None
                if request.depth:
                    parent = db.execute(
                        "select output_json,agent_name,depth from public.agent_runs where tenant_id=%s and workflow_id=%s and id=%s and status in ('succeeded','degraded')",
                        (workflow["tenant_id"], workflow["id"], request.parent_run_id),
                    ).fetchone()
                    if (
                        not parent
                        or parent["depth"] != request.depth - 1
                        or parent["agent_name"] != steps[request.depth - 1]
                    ):
                        raise AgentRuntimeError("agent_parent_invalid")
                    previous = CATALOG[steps[request.depth - 1]].output_schema.model_validate(
                        parent["output_json"]
                    )
                elif request.parent_run_id is not None:
                    raise AgentRuntimeError("agent_parent_invalid")
                if workflow["definition_version"] == SPECIALIST_VERSION:
                    source = self._specialist_projection(db, workflow)
                    if previous is not None and not isinstance(previous, TriageAnalysis):
                        raise AgentRuntimeError("agent_parent_invalid")
                    payload: AnalysisInput | SpecialistInput = SpecialistInput(
                        context_ref=workflow["context_ref"],
                        content_hash=source["content_hash"],
                        content=source["content"],
                        evidence_refs=source["evidence_refs"],
                        previous=previous,
                    )
                else:
                    snapshot = self._snapshot(
                        db,
                        workflow["tenant_id"],
                        workflow["opportunity_id"],
                        workflow["context_ref"],
                    )
                    if previous is not None and not isinstance(previous, AnalysisOutput):
                        raise AgentRuntimeError("agent_parent_invalid")
                    payload = self._input(snapshot, previous)
                prompt = payload.model_dump_json()
                if len(prompt.encode()) > definition.max_input_bytes:
                    raise AgentRuntimeError("agent_input_too_large")
                estimate = estimate_usd(workflow["model_id"], len(prompt.encode()))
                spent = db.execute(
                    "select coalesce(sum(greatest(b.estimated_usd,coalesce(b.actual_usd,b.estimated_usd))),0) amount from public.ai_budget_reservations b join public.agent_runs r on r.tenant_id=b.tenant_id and r.id=b.run_id where r.tenant_id=%s and r.workflow_id=%s and b.status in ('reserved','settled')",
                    (workflow["tenant_id"], workflow["id"]),
                ).fetchone()
                if spent and spent["amount"] + estimate > workflow["budget_limit_usd"]:
                    raise AgentRuntimeError("agent_chain_budget_exceeded")
                run_id = uuid4()
                db.execute(
                    "insert into public.agent_runs(id,tenant_id,opportunity_id,context_ref,correlation_id,agent_name,agent_version,model_id,prompt_hash,output_schema_version,generation_mode,status,workflow_id,parent_run_id,depth,definition_hash,input_schema_version,checkpoint,lease_token) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'agno_openai','running',%s,%s,%s,%s,%s,'prepared',%s)",
                    (
                        run_id,
                        workflow["tenant_id"],
                        workflow["opportunity_id"],
                        workflow["context_ref"],
                        workflow["correlation_id"],
                        definition.agent_id,
                        definition.version,
                        workflow["model_id"],
                        digest({"input": prompt, "definition": definition.definition_hash}),
                        definition.output_schema_version,
                        workflow["id"],
                        request.parent_run_id,
                        request.depth,
                        definition.definition_hash,
                        definition.input_schema_version,
                        claimed["lease_token"],
                    ),
                )
                decision = QuotaGuard(self.url).reserve_on(
                    db, workflow["tenant_id"], run_id, estimate
                )
                if not decision.allowed:
                    raise AgentRuntimeError(decision.code, 429)
                db.execute(
                    "update public.agent_workflows set root_run_id=coalesce(root_run_id,%s) where tenant_id=%s and id=%s",
                    (run_id, workflow["tenant_id"], workflow["id"]),
                )
                return run_id, payload
            except (AgentRuntimeError, ValueError) as error:
                code = (
                    error.code if isinstance(error, AgentRuntimeError) else "agent_contract_invalid"
                )
                self._stop(db, workflow, "blocked", code)
                return UUID(int=0), AnalysisInput(
                    context_ref=workflow["context_ref"],
                    content_hash="",
                    content="",
                    evidence_refs=[],
                )

    def _dispatch(self, claimed: dict[str, Any], run: UUID) -> None:
        with self._db() as db:
            workflow = self._fence(db, claimed)
            self._authorize(db, workflow)
            if workflow["deadline_at"] <= datetime.now(UTC):
                raise AgentRuntimeError("agent_chain_timeout")
            if workflow["definition_version"] == SPECIALIST_VERSION:
                self._specialist_projection(db, workflow)
            else:
                self._snapshot(
                    db, workflow["tenant_id"], workflow["opportunity_id"], workflow["context_ref"]
                )
            db.execute(
                "update public.agent_runs set checkpoint='dispatched' where tenant_id=%s and id=%s and lease_token=%s and checkpoint='prepared'",
                (workflow["tenant_id"], run, claimed["lease_token"]),
            )

    def _heartbeat(self, claimed: dict[str, Any]) -> bool:
        with self._db() as db:
            row = db.execute(
                "update public.jobs set lease_until=clock_timestamp()+interval '30 seconds',updated_at=now() where tenant_id=%s and id=%s and lease_token=%s and status='running' and lease_until>clock_timestamp() returning id",
                (claimed["tenant_id"], claimed["id"], claimed["lease_token"]),
            ).fetchone()
        return bool(row)

    async def _invoke(
        self, claimed: dict[str, Any], payload: AnalysisInput | SpecialistInput
    ) -> AgentOutcome:
        request = AgentJob.model_validate(claimed["payload"])
        task = asyncio.create_task(
            self.executor.execute(
                CATALOG[request.agent_id], payload, claimed["workflow"]["model_id"]
            )
        )

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(5)
                if not await asyncio.to_thread(self._heartbeat, claimed):
                    raise LeaseLost

        pulse = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait(
                {task, pulse},
                timeout=CATALOG[request.agent_id].timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise TimeoutError
            if pulse in done:
                await pulse
            return await task
        finally:
            task.cancel()
            pulse.cancel()
            with suppress(asyncio.CancelledError, LeaseLost):
                await pulse
            with suppress(asyncio.CancelledError, Exception):
                await task

    def _finish(
        self,
        claimed: dict[str, Any],
        run: UUID,
        payload: AnalysisInput | SpecialistInput,
        outcome: AgentOutcome,
    ) -> None:
        with self._db() as db:
            # Usage is durable even if cancellation/access changes prevent publication.
            record_usage_on(db, claimed["tenant_id"], run, outcome.usage)
        with self._db() as db:
            workflow = self._fence(db, claimed)
            self._authorize(db, workflow)
            if workflow["deadline_at"] <= datetime.now(UTC):
                raise AgentRuntimeError("agent_chain_timeout")
            request = AgentJob.model_validate(claimed["payload"])
            if workflow["definition_version"] == SPECIALIST_VERSION:
                self._specialist_projection(db, workflow)
            else:
                self._snapshot(
                    db, workflow["tenant_id"], workflow["opportunity_id"], workflow["context_ref"]
                )
            output = CATALOG[request.agent_id].output_schema.model_validate(outcome.output)
            if isinstance(payload, SpecialistInput) and isinstance(
                output, (TriageAnalysis, DiagnosisAnalysis)
            ):
                try:
                    validate_grounding(output, payload)
                except ValueError as error:
                    raise AgentRuntimeError(str(error)) from error
            if not set(output.evidence_refs) <= set(payload.evidence_refs):
                raise AgentRuntimeError("agent_evidence_invalid")
            request = AgentJob.model_validate(claimed["payload"])
            status = "degraded" if outcome.degraded else "succeeded"
            db.execute(
                "update public.agent_runs set status=%s,checkpoint='completed',output_json=%s,finished_at=now(),generation_mode=%s,error_code=%s where tenant_id=%s and id=%s and lease_token=%s",
                (
                    status,
                    Jsonb(output.model_dump(mode="json")),
                    "deterministic_fallback" if outcome.degraded else "agno_openai",
                    "model_not_configured" if outcome.degraded else None,
                    workflow["tenant_id"],
                    run,
                    claimed["lease_token"],
                ),
            )
            db.execute(
                "update public.jobs set status='succeeded',finished_at=now(),updated_at=now(),lease_owner=null,lease_token=null,lease_until=null where tenant_id=%s and id=%s",
                (workflow["tenant_id"], claimed["id"]),
            )
            steps = sequence(workflow["definition_version"])
            if request.depth + 1 < len(steps) and not (
                isinstance(output, TriageAnalysis) and output.route == "human_review"
            ):
                self._enqueue(db, workflow, steps[request.depth + 1], request.depth + 1, run)
            else:
                degraded = db.execute(
                    "select 1 from public.agent_runs where tenant_id=%s and workflow_id=%s and status='degraded' limit 1",
                    (workflow["tenant_id"], workflow["id"]),
                ).fetchone()
                db.execute(
                    "update public.agent_workflows set status=%s,finished_at=now() where tenant_id=%s and id=%s",
                    (
                        "degraded" if degraded else "succeeded",
                        workflow["tenant_id"],
                        workflow["id"],
                    ),
                )

    def _receipt(self, claimed: dict[str, Any]) -> AgentAttemptReceipt:
        with self._db() as db:
            row = db.execute(
                "select status from public.jobs where tenant_id=%s and id=%s",
                (claimed["tenant_id"], claimed["id"]),
            ).fetchone()
        return AgentAttemptReceipt(claimed["id"], bool(row and row["status"] == "succeeded"))

    def process_next(self) -> AgentAttemptReceipt | None:
        self.recover()
        claimed = self._claim()
        if not claimed:
            return None
        run: UUID | None = None
        try:
            run, payload = self._prepare(claimed)
            if run.int == 0:
                return self._receipt(claimed)
            self._dispatch(claimed, run)
            outcome = asyncio.run(self._invoke(claimed, payload))
            self._finish(claimed, run, payload, outcome)
        except LeaseLost:
            # A cancellation or reclaim already owns termination. Never overwrite it.
            pass
        except Exception as error:  # noqa: BLE001 - no exception text/customer payload in logs
            if isinstance(error, InvalidAgentOutput) and run:
                with self._db() as db:
                    record_usage_on(db, claimed["tenant_id"], run, error.usage)
            code = (
                error.code
                if isinstance(error, AgentRuntimeError)
                else "agent_timeout"
                if isinstance(error, TimeoutError)
                else "agent_output_invalid"
                if isinstance(error, InvalidAgentOutput)
                else "agent_model_result_unknown"
            )
            with self._db() as db:
                try:
                    workflow = self._fence(db, claimed)
                except LeaseLost:
                    pass
                else:
                    self._stop(
                        db,
                        workflow,
                        "blocked" if isinstance(error, AgentRuntimeError) else "failed",
                        code,
                    )
        return self._receipt(claimed)
