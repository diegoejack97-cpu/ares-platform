"""One bounded interpretation per finding revision; uncertain calls are never replayed."""

# ruff: noqa: E501
import asyncio
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.agents.catalog import CATALOG, digest
from ares.agents.executor import AgentExecutor, AgnoExecutor, InvalidAgentOutput
from ares.agents.specialists import DiagnosisAnalysis, SpecialistInput, validate_grounding
from ares.ai.quotas import QuotaGuard, estimate_usd
from ares.ai.usage import UsageObservation, record_usage_on
from ares.decision.execution_guard import ExecutionBlocked, check_execution_contract
from ares.intelligence.context_builder import ContextBuilder, ContextUnavailable
from ares.sentinels.findings import predicate, snapshot_expression


class SentinelInterpreter:
    def __init__(
        self, url: str, model: str, api_key: str = "", executor: AgentExecutor | None = None
    ):
        self.url, self.model, self.executor = url, model, executor or AgnoExecutor(api_key)

    @staticmethod
    def current_on(
        db: psycopg.Connection[Any], tenant: UUID, finding: UUID, revision: int
    ) -> dict[str, Any] | None:
        check_execution_contract(db, tenant)
        db.execute(
            "select s.rule_id from public.sentinel_schedules s join public.sentinel_findings f on f.tenant_id=s.tenant_id and f.rule_id=s.rule_id where f.tenant_id=%s and f.id=%s for share of s",
            (tenant, finding),
        ).fetchone()
        row = db.execute(
            "select f.*,s.kind,s.threshold_hours,s.criteria_json,s.version,s.updated_by,s.interpret_with_ai,s.enabled,s.archived_at from public.sentinel_findings f join public.sentinel_schedules s on s.tenant_id=f.tenant_id and s.rule_id=f.rule_id where f.tenant_id=%s and f.id=%s for update of f",
            (tenant, finding),
        ).fetchone()
        if not row or row["revision"] != revision or row["status"] not in {"open", "updated"}:
            return None
        quota = db.execute(
            "select agent_slots,sentinel_slots from public.tenant_quotas where tenant_id=%s for update",
            (tenant,),
        ).fetchone()
        rank = db.execute(
            "select count(*) count from public.sentinel_schedules where tenant_id=%s and enabled and archived_at is null and (created_at,rule_id)<=(select created_at,rule_id from public.sentinel_schedules where tenant_id=%s and rule_id=%s)",
            (tenant, tenant, row["rule_id"]),
        ).fetchone()
        if (
            not quota
            or quota["agent_slots"] < 1
            or not rank
            or rank["count"] > quota["sentinel_slots"]
            or not row["enabled"]
            or row["archived_at"]
            or not row["interpret_with_ai"]
            or str(row["version"]) != row["rule_version"]
        ):
            raise ExecutionBlocked("sentinel_interpretation_revoked")
        # Autonomous identity is the configured rule, scoped to its tenant and purpose.
        where, values = predicate(row)
        observed = db.execute(
            f"select {snapshot_expression(row['kind'])} evidence from public.ares_opportunities o left join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id where o.id=%s and {where}",
            (row["threshold_hours"], row["opportunity_id"], *values),
        ).fetchone()
        if not observed or observed["evidence"] != row["evidence"]:
            raise ExecutionBlocked("sentinel_context_stale")
        return dict(row)

    def process(self, tenant: UUID, payload: dict[str, Any]) -> None:
        finding, revision = UUID(payload["finding_id"]), int(payload["revision"])
        definition = CATALOG["sentinel-interpreter"]
        run = None
        usage = UsageObservation()
        dispatched = False
        try:
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                row = self.current_on(db, tenant, finding, revision)
                if not row:
                    return
                if row["interpretation_run_id"]:
                    # Recovery after worker failure closes uncertainty rather than billing twice.
                    if row["interpretation_status"] == "running":
                        db.execute(
                            "update public.sentinel_findings set interpretation_status='failed' where tenant_id=%s and id=%s",
                            (tenant, finding),
                        )
                        db.execute(
                            "update public.agent_runs set status='failed',error_code='sentinel_outcome_unknown',finished_at=now() where tenant_id=%s and id=%s and status='running'",
                            (tenant, row["interpretation_run_id"]),
                        )
                    return
                source = ContextBuilder.sentinel_context_on(
                    db, tenant, UUID(payload["context_ref"]), finding, revision
                )
                inputs = SpecialistInput(
                    context_ref=source["context_ref"],
                    content_hash=source["content_hash"],
                    content=source["content"],
                    evidence_refs=source["evidence_refs"],
                )
                run = uuid4()
                db.execute(
                    "insert into public.agent_runs(id,tenant_id,opportunity_id,correlation_id,agent_name,agent_version,model_id,prompt_hash,output_schema_version,input_schema_version,definition_hash,sentinel_context_ref,generation_mode,status,checkpoint) values(%s,%s,%s,%s,'sentinel-interpreter',%s,%s,%s,%s,%s,%s,%s,'agno_openai','running','prepared')",
                    (
                        run,
                        tenant,
                        row["opportunity_id"],
                        row["correlation_id"],
                        definition.version,
                        self.model,
                        digest(inputs.model_dump()),
                        definition.output_schema_version,
                        definition.input_schema_version,
                        definition.definition_hash,
                        source["context_ref"],
                    ),
                )
                db.execute(
                    "update public.sentinel_findings set interpretation_status='running',interpretation_run_id=%s where tenant_id=%s and id=%s",
                    (run, tenant, finding),
                )
                decision = QuotaGuard(self.url).reserve_on(
                    db,
                    tenant,
                    run,
                    estimate_usd(self.model, len(inputs.model_dump_json().encode())),
                )
                if not decision.allowed:
                    usage = UsageObservation(status="not_called")
                    self.finish_on(
                        db, tenant, finding, revision, run, "degraded", decision.code, usage
                    )
                    return
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                current = self.current_on(db, tenant, finding, revision)
                if (
                    not current
                    or current["interpretation_run_id"] != run
                    or current["interpretation_status"] != "running"
                ):
                    raise ExecutionBlocked("sentinel_context_stale")
                db.execute(
                    "update public.agent_runs set checkpoint='dispatched' where tenant_id=%s and id=%s",
                    (tenant, run),
                )
            dispatched = True

            async def execute():
                async with asyncio.timeout(definition.timeout_seconds):
                    return await self.executor.execute(definition, inputs, self.model)

            result = asyncio.run(execute())
            usage = result.usage
            if not isinstance(result.output, DiagnosisAnalysis):
                raise ValueError("sentinel_output_invalid")
            validate_grounding(result.output, inputs)
            output = result.output.model_dump(mode="json")
            output["limitations"] = list(
                dict.fromkeys([*source["cuts"], *result.output.limitations])
            )[:8]
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                current = self.current_on(db, tenant, finding, revision)
                if (
                    not current
                    or current["interpretation_run_id"] != run
                    or current["interpretation_status"] != "running"
                ):
                    raise ExecutionBlocked("sentinel_context_stale")
                state = "degraded" if result.degraded else "ready"
                self.finish_on(
                    db,
                    tenant,
                    finding,
                    revision,
                    run,
                    state,
                    None,
                    usage,
                    output,
                )
        except (
            ExecutionBlocked,
            ContextUnavailable,
            ValueError,
            TimeoutError,
            InvalidAgentOutput,
        ) as error:
            if isinstance(error, InvalidAgentOutput):
                usage = error.usage
            if not dispatched:
                usage = UsageObservation(status="not_called")
            code = getattr(error, "code", None) or type(error).__name__
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                self.finish_on(
                    db,
                    tenant,
                    finding,
                    revision,
                    run,
                    "degraded" if not dispatched else "failed",
                    code,
                    usage,
                )
        except Exception:
            # Model/network errors are redacted; preserve the objective finding.
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                self.finish_on(
                    db, tenant, finding, revision, run, "failed", "sentinel_model_failed", usage
                )

    @staticmethod
    def finish_on(
        db: psycopg.Connection[Any],
        tenant: UUID,
        finding: UUID,
        revision: int,
        run: UUID | None,
        state: str,
        code: str | None,
        usage: UsageObservation,
        output: dict[str, Any] | None = None,
    ) -> None:
        db.execute(
            "select s.rule_id from public.sentinel_schedules s join public.sentinel_findings f on f.tenant_id=s.tenant_id and f.rule_id=s.rule_id where f.tenant_id=%s and f.id=%s for update of s",
            (tenant, finding),
        ).fetchone()
        if (
            run
            and db.execute(
                "select 1 from public.agent_runs where tenant_id=%s and id=%s", (tenant, run)
            ).fetchone()
        ):
            record_usage_on(db, tenant, run, usage)
            db.execute(
                "update public.agent_runs set status=%s,error_code=%s,output_json=%s,finished_at=now() where tenant_id=%s and id=%s",
                (
                    "succeeded" if state == "ready" else state,
                    code,
                    Jsonb(output) if output else None,
                    tenant,
                    run,
                ),
            )
        db.execute(
            "update public.sentinel_findings set interpretation_status=%s,interpretation_json=%s where tenant_id=%s and id=%s and revision=%s and status in ('open','updated') and interpretation_status in ('pending','running') and (interpretation_run_id is null or interpretation_run_id=%s)",
            (state, Jsonb(output) if output else None, tenant, finding, revision, run),
        )
        db.execute(
            "update public.sentinel_schedules s set last_error_code=%s where tenant_id=%s and exists(select 1 from public.sentinel_findings f where f.tenant_id=s.tenant_id and f.rule_id=s.rule_id and f.id=%s and f.revision=%s and f.rule_version=s.version::text)",
            (code, tenant, finding, revision),
        )
