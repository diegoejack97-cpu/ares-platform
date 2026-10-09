"""Personal portfolio orchestration. Models cannot choose scope, SQL or execution."""

# ruff: noqa: E501
import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.agents.catalog import CATALOG
from ares.agents.commercial_contracts import CommercialConfig, PortfolioRequest, validate_commercial
from ares.agents.executor import AgentExecutor, AgnoExecutor
from ares.agents.runtime import AgentRuntimeError
from ares.agents.specialists import SpecialistInput
from ares.ai.quotas import QuotaGuard, estimate_usd
from ares.ai.usage import UsageObservation, record_usage_on
from ares.auth.models import AuthenticatedUser
from ares.decision.execution_guard import ExecutionBlocked, check_execution_contract
from ares.intelligence.context_builder import ContextBuilder, encode, fingerprint
from ares.sentinels.models import SentinelCalendar
from ares.sentinels.scheduling import next_calendar_at


class CommercialService:
    def __init__(
        self, url: str, model: str = "gpt-5.4", key: str = "", executor: AgentExecutor | None = None
    ):
        self.url, self.model = url, model
        self.executor = executor or AgnoExecutor(key)

    def config_on(
        self, db: psycopg.Connection[Any], user: AuthenticatedUser, *, execute: bool = False
    ) -> tuple[str, dict[str, Any] | None]:
        role = ContextBuilder.authorize(db, user)
        config = db.execute(
            "select * from public.commercial_routines where tenant_id=%s for share",
            (user.tenant_id,),
        ).fetchone()
        if execute:
            check_execution_contract(db, user.tenant_id)
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s for share",
                (user.tenant_id,),
            ).fetchone()
            if (
                role == "auditor"
                or not config
                or not config["enabled"]
                or not quota
                or quota["agent_slots"] < 3
            ):
                raise AgentRuntimeError("commercial_routine_unavailable", 403)
        return role, dict(config) if config else None

    def configuration(self, user: AuthenticatedUser) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role, config = self.config_on(db, user)
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
        return {
            "version": config["version"] if config else 0,
            "config": config,
            "can_configure": role == "admin",
            "available": bool(quota and quota["agent_slots"] >= 3),
        }

    def configure(self, user: AuthenticatedUser, command: CommercialConfig) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (str(user.tenant_id) + ":commercial-config",),
            )
            role, prior = self.config_on(db, user)
            if role != "admin":
                raise AgentRuntimeError("commercial_admin_required", 403)
            if (prior["version"] if prior else 0) != command.expected_version:
                raise AgentRuntimeError("commercial_config_conflict")
            check_execution_contract(db, user.tenant_id)
            quota = db.execute(
                "select agent_slots from public.tenant_quotas where tenant_id=%s for share",
                (user.tenant_id,),
            ).fetchone()
            if command.enabled and (not quota or quota["agent_slots"] < 3):
                raise AgentRuntimeError("commercial_capacity_required", 403)
            zone_row = db.execute(
                "select timezone from public.tenants where id=%s", (user.tenant_id,)
            ).fetchone()
            assert zone_row
            zone = zone_row["timezone"]
            next_at = next_calendar_at(datetime.now(UTC), zone, time(0), 1440, command.calendar)
            db.execute(
                "insert into public.commercial_routines(tenant_id,enabled,recommendations_enabled,proactive_enabled,criterion,currency,calendar_json,cooldown_hours,daily_proposal_limit,updated_by,next_run_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id) do update set enabled=excluded.enabled,recommendations_enabled=excluded.recommendations_enabled,proactive_enabled=excluded.proactive_enabled,criterion=excluded.criterion,currency=excluded.currency,calendar_json=excluded.calendar_json,cooldown_hours=excluded.cooldown_hours,daily_proposal_limit=excluded.daily_proposal_limit,updated_by=excluded.updated_by,next_run_at=excluded.next_run_at,version=commercial_routines.version+1,updated_at=now()",
                (
                    user.tenant_id,
                    command.enabled,
                    command.recommendations_enabled,
                    command.proactive_enabled,
                    command.criterion,
                    command.currency,
                    Jsonb(command.calendar.model_dump(mode="json")),
                    command.cooldown_hours,
                    command.daily_proposal_limit,
                    user.user_id,
                    next_at,
                ),
            )
            db.execute(
                "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'user',%s,'commercial.configure',%s,'ares',%s)",
                (
                    user.tenant_id,
                    str(user.user_id),
                    uuid4(),
                    Jsonb(command.model_dump(mode="json")),
                ),
            )
        return self.configuration(user)

    def latest(self, user: AuthenticatedUser, request: PortfolioRequest) -> dict[str, Any]:
        source = ContextBuilder(self.url).portfolio(user, request.criterion, request.currency)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role, config = self.config_on(db, user)
            eligible = False
            try:
                self.config_on(db, user, execute=True)
                eligible = True
            except (AgentRuntimeError, ExecutionBlocked):
                pass
            row = db.execute(
                "select * from public.portfolio_analyses where tenant_id=%s and actor_id=%s and request_hash=%s order by created_at desc limit 1",
                (user.tenant_id, user.user_id, fingerprint(request.model_dump())),
            ).fetchone()
            runs = (
                db.execute(
                    "select id,agent_name,status from public.agent_runs where tenant_id=%s and correlation_id=%s order by started_at,id",
                    (user.tenant_id, row["correlation_id"]),
                ).fetchall()
                if row
                else []
            )
        current = bool(
            row
            and config
            and eligible
            and config["enabled"]
            and row["config_version"] == config["version"]
            and row["actor_role"] == role
            and row["relevant_hash"] == source["relevant_hash"]
            and row["valid_until"] > datetime.now(UTC)
        )
        return {
            "state": row["status"] if current and row else "stale" if row else "not_generated",
            "analysis_id": row["id"] if row else None,
            "can_request": eligible,
            "criterion": request.criterion,
            "currency": request.currency,
            "ranking": row["ranking_json"] if current and row else None,
            "briefing": row["briefing_json"] if current and row else None,
            "created_at": row["created_at"] if row else None,
            "valid_until": row["valid_until"] if row else None,
            "context_ref": row["context_ref"] if current and row else None,
            "run_ids": [item["id"] for item in runs] if current and row else [],
            "error_code": row["error_code"] if current and row else None,
            "source": source["source"],
            "total": source["result"].get("metrics", {}).get("total", 0),
            "currency_totals": source["result"].get("metrics", {}).get("currencies", []),
            "coverage_note": "Seleção sobre todo o espelho autorizado, limitada pelo contexto. CRM sem homologação de completude.",
            "candidates": json.loads(source["content"])["matches"],
            "coverage": source["metadata"],
            "scope": "own_portfolio" if role == "seller" else "tenant",
        }

    def start(self, user: AuthenticatedUser, request: PortfolioRequest) -> dict[str, Any]:
        source = ContextBuilder(self.url).portfolio(user, request.criterion, request.currency)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (str(user.tenant_id) + str(user.user_id) + ":portfolio",),
            )
            role, config = self.config_on(db, user, execute=True)
            assert config
            existing = db.execute(
                "select id from public.portfolio_analyses where tenant_id=%s and actor_id=%s and request_hash=%s and relevant_hash=%s and config_version=%s and actor_role=%s and valid_until>now() and status in ('queued','running','ready','degraded','failed','blocked') order by created_at desc limit 1",
                (
                    user.tenant_id,
                    user.user_id,
                    fingerprint(request.model_dump()),
                    source["relevant_hash"],
                    config["version"],
                    role,
                ),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "reused": True}
            prior = db.execute(
                "select 1 from public.portfolio_analyses where tenant_id=%s and actor_id=%s and created_at>now()-interval '1 minute'",
                (user.tenant_id, user.user_id),
            ).fetchone()
            if prior:
                raise AgentRuntimeError("portfolio_cooldown", 429)
            id, correlation = uuid4(), uuid4()
            db.execute(
                "insert into public.portfolio_analyses(id,tenant_id,actor_id,criterion,currency,request_hash,relevant_hash,context_ref,config_version,actor_role,correlation_id,valid_until) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+interval '15 minutes')",
                (
                    id,
                    user.tenant_id,
                    user.user_id,
                    request.criterion,
                    request.currency,
                    fingerprint(request.model_dump()),
                    source["relevant_hash"],
                    source["context_ref"],
                    config["version"],
                    role,
                    correlation,
                ),
            )
            self.enqueue(db, user.tenant_id, id, correlation, 0)
        return {"id": id, "reused": False}

    @staticmethod
    def enqueue(
        db: psycopg.Connection[Any], tenant: UUID, id: UUID, correlation: UUID, stage: int
    ) -> None:
        db.execute(
            "insert into public.jobs(tenant_id,kind,payload,correlation_id) values(%s,'commercial.analyze',%s,%s)",
            (tenant, Jsonb({"analysis_id": str(id), "stage": stage}), correlation),
        )

    def process(self, tenant: UUID, payload: dict[str, Any]) -> None:
        id, stage = UUID(payload["analysis_id"]), int(payload["stage"])
        run = None
        usage = UsageObservation(status="not_called")
        try:
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                row = db.execute(
                    "select * from public.portfolio_analyses where tenant_id=%s and id=%s for update",
                    (tenant, id),
                ).fetchone()
                if not row or row["stage"] != stage or row["status"] not in {"queued", "running"}:
                    return
                user = AuthenticatedUser(
                    tenant_id=tenant, user_id=row["actor_id"], role=row["actor_role"]
                )
                role, config = self.config_on(db, user, execute=True)
                if (
                    not config
                    or config["version"] != row["config_version"]
                    or role != row["actor_role"]
                    or row["valid_until"] <= datetime.now(UTC)
                ):
                    raise AgentRuntimeError("commercial_authority_stale")
                prior = db.execute(
                    "select id from public.agent_runs where tenant_id=%s and correlation_id=%s and agent_name=%s",
                    (
                        tenant,
                        row["correlation_id"],
                        ("portfolio-prioritizer", "commercial-analyst")[stage],
                    ),
                ).fetchone()
                if prior and not payload.get("recovered"):
                    return
                if row["status"] == "running" and not payload.get("recovered"):
                    return
                if prior:
                    db.execute(
                        "update public.portfolio_analyses set status='failed',error_code='commercial_outcome_unknown' where tenant_id=%s and id=%s",
                        (tenant, id),
                    )
                    return
                db.execute(
                    "update public.portfolio_analyses set status='running' where tenant_id=%s and id=%s",
                    (tenant, id),
                )
            source = ContextBuilder(self.url).portfolio(user, row["criterion"], row["currency"])
            if source["relevant_hash"] != row["relevant_hash"]:
                raise AgentRuntimeError("commercial_context_stale")
            content = json.loads(source["content"])
            if stage:
                content["prior_ranking_interpretation"] = row["ranking_json"]
            inputs = SpecialistInput(
                context_ref=row["context_ref"],
                content_hash=fingerprint(content),
                content=encode(content),
                evidence_refs=source["candidate_refs"],
            )
            definition = CATALOG[("portfolio-prioritizer", "commercial-analyst")[stage]]
            run = uuid4()
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                self.config_on(db, user, execute=True)
                parent = db.execute(
                    "select id from public.agent_runs where tenant_id=%s and correlation_id=%s order by started_at limit 1",
                    (tenant, row["correlation_id"]),
                ).fetchone()
                db.execute(
                    "insert into public.agent_runs(id,tenant_id,context_ref,correlation_id,agent_name,agent_version,definition_hash,parent_run_id,prompt_hash,input_schema_version,output_schema_version,generation_mode,status,checkpoint) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,'specialist-input.v1','commercial-output.v1','agno_openai','running','prepared')",
                    (
                        run,
                        tenant,
                        row["context_ref"],
                        row["correlation_id"],
                        definition.agent_id,
                        definition.version,
                        definition.definition_hash,
                        parent["id"] if parent else None,
                        inputs.content_hash,
                    ),
                )
                if (
                    not QuotaGuard(self.url)
                    .reserve_on(
                        db,
                        tenant,
                        run,
                        estimate_usd(self.model, len(inputs.model_dump_json().encode())),
                    )
                    .allowed
                ):
                    db.commit()
                    raise AgentRuntimeError("commercial_budget_exceeded")
                db.execute(
                    "update public.portfolio_analyses set status='running' where tenant_id=%s and id=%s",
                    (tenant, id),
                )
                db.execute(
                    "update public.agent_runs set checkpoint='dispatched' where tenant_id=%s and id=%s",
                    (tenant, run),
                )
            usage = UsageObservation()

            async def execute():
                async with asyncio.timeout(95):
                    return await self.executor.execute(definition, inputs, self.model)

            result = asyncio.run(execute())
            usage = result.usage
            result = result.__class__(
                definition.output_schema.model_validate(result.output),
                result.usage,
                result.degraded,
            )
            validate_commercial(result.output, inputs)
            current = ContextBuilder(self.url).portfolio(user, row["criterion"], row["currency"])
            if current["relevant_hash"] != row["relevant_hash"]:
                raise AgentRuntimeError("commercial_context_stale")
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                role, config = self.config_on(db, user, execute=True)
                if (
                    not config
                    or config["version"] != row["config_version"]
                    or role != row["actor_role"]
                    or row["valid_until"] <= datetime.now(UTC)
                ):
                    raise AgentRuntimeError("commercial_authority_stale")
                record_usage_on(db, tenant, run, usage)
                db.execute(
                    "update public.agent_runs set status=%s,output_json=%s,checkpoint='completed',finished_at=now() where tenant_id=%s and id=%s",
                    (
                        "degraded" if result.degraded else "succeeded",
                        Jsonb(result.output.model_dump(mode="json")),
                        tenant,
                        run,
                    ),
                )
                column = "ranking_json" if stage == 0 else "briefing_json"
                db.execute(
                    f"update public.portfolio_analyses set {column}=%s,status=%s,stage=%s where tenant_id=%s and id=%s",
                    (
                        Jsonb(result.output.model_dump(mode="json")),
                        "queued" if stage == 0 else "degraded" if result.degraded else "ready",
                        stage + 1,
                        tenant,
                        id,
                    ),
                )
                if stage == 1:
                    degraded = db.execute(
                        "select exists(select 1 from public.agent_runs where tenant_id=%s and correlation_id=%s and status='degraded') partial",
                        (tenant, row["correlation_id"]),
                    ).fetchone()
                    if degraded and degraded["partial"]:
                        db.execute(
                            "update public.portfolio_analyses set status='degraded' where tenant_id=%s and id=%s",
                            (tenant, id),
                        )
                if stage == 0:
                    self.enqueue(db, tenant, id, row["correlation_id"], 1)
            if stage == 1:
                with suppress(AgentRuntimeError, ExecutionBlocked):
                    self.propose(
                        user,
                        [
                            str(item["opportunity_id"])
                            for item in (row["ranking_json"] or {}).get("ranking", [])
                        ],
                        "portfolio",
                    )
        except Exception as error:
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                if (
                    run
                    and db.execute(
                        "select 1 from public.agent_runs where tenant_id=%s and id=%s",
                        (tenant, run),
                    ).fetchone()
                ):
                    record_usage_on(db, tenant, run, usage)
                    db.execute(
                        "update public.agent_runs set status='failed',error_code=%s,finished_at=now() where tenant_id=%s and id=%s and status='running'",
                        (getattr(error, "code", "commercial_analysis_failed"), tenant, run),
                    )
                db.execute(
                    "update public.portfolio_analyses set status='failed',error_code=%s where tenant_id=%s and id=%s and status in ('queued','running')",
                    (getattr(error, "code", "commercial_analysis_failed"), tenant, id),
                )

    def propose(self, user: AuthenticatedUser, ids: list[str], trigger: str) -> int:
        from ares.decision.proposal_agents import decision_fingerprint_on

        count = 0
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (str(user.tenant_id) + ":commercial-proposals",),
            )
            role, config = self.config_on(db, user, execute=True)
            if (
                not config
                or not config["proactive_enabled"]
                or not config["recommendations_enabled"]
            ):
                return 0
            for raw in ids[:20]:
                opportunity = UUID(raw)
                scope = db.execute(
                    "select state,owner_user_id from public.ares_opportunities where tenant_id=%s and id=%s",
                    (user.tenant_id, opportunity),
                ).fetchone()
                if (
                    not scope
                    or scope["state"] not in {"prioritized", "awaiting_decision"}
                    or (role == "seller" and scope["owner_user_id"] != user.user_id)
                ):
                    continue
                recent = db.execute(
                    "select count(*) n from public.commercial_proposals p join public.tenants t on t.id=p.tenant_id where p.tenant_id=%s and (p.created_at at time zone t.timezone)::date=(now() at time zone t.timezone)::date",
                    (user.tenant_id,),
                ).fetchone()
                assert recent
                if recent["n"] >= config["daily_proposal_limit"]:
                    break
                if db.execute(
                    "select 1 from public.commercial_proposals where tenant_id=%s and opportunity_id=%s and created_at>now()-make_interval(hours=>%s)",
                    (user.tenant_id, opportunity, config["cooldown_hours"]),
                ).fetchone():
                    continue
                hash = decision_fingerprint_on(db, user.tenant_id, opportunity)
                proposal = db.execute(
                    "insert into public.commercial_proposals(tenant_id,opportunity_id,actor_id,context_hash,trigger_kind) values(%s,%s,%s,%s,%s) on conflict(tenant_id,opportunity_id,context_hash) do nothing returning id",
                    (user.tenant_id, opportunity, user.user_id, hash, trigger),
                ).fetchone()
                if proposal:
                    db.execute(
                        "insert into public.jobs(tenant_id,kind,payload,correlation_id) values(%s,'commercial.propose',%s,%s)",
                        (user.tenant_id, Jsonb({"proposal_id": str(proposal["id"])}), uuid4()),
                    )
                    count += 1
        return count

    def scan(self) -> None:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            configs = db.execute(
                "select r.*,t.timezone,m.role::text actor_role from public.commercial_routines r join public.tenants t on t.id=r.tenant_id join public.memberships m on m.tenant_id=r.tenant_id and m.user_id=r.updated_by and m.active where r.enabled and r.next_run_at<=now() and m.role='admin' order by r.next_run_at limit 10"
            ).fetchall()
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            proactive = db.execute(
                "select r.tenant_id,r.updated_by from public.commercial_routines r join public.memberships m on m.tenant_id=r.tenant_id and m.user_id=r.updated_by and m.active where r.enabled and r.recommendations_enabled and r.proactive_enabled and m.role='admin' order by r.tenant_id limit 100"
            ).fetchall()
        for setting in proactive:
            actor = AuthenticatedUser(
                tenant_id=setting["tenant_id"], user_id=setting["updated_by"], role="admin"
            )
            try:
                with psycopg.connect(self.url, row_factory=dict_row) as db:
                    findings = db.execute(
                        "select opportunity_id from public.sentinel_findings where tenant_id=%s and status in ('open','updated') order by last_seen_at desc limit 20",
                        (actor.tenant_id,),
                    ).fetchall()
                self.propose(actor, [str(item["opportunity_id"]) for item in findings], "finding")
            except Exception:
                pass  # One tenant must not stop other tenants' worker ticks.
        for config in configs:
            user = AuthenticatedUser(
                tenant_id=config["tenant_id"], user_id=config["updated_by"], role="admin"
            )
            with suppress(Exception):
                self.start(
                    user,
                    PortfolioRequest(criterion=config["criterion"], currency=config["currency"]),
                )
            with psycopg.connect(self.url) as db:
                next_at = next_calendar_at(
                    datetime.now(UTC),
                    config["timezone"],
                    time(0),
                    1440,
                    SentinelCalendar.model_validate(config["calendar_json"]),
                )
                db.execute(
                    "update public.commercial_routines set next_run_at=%s where tenant_id=%s and version=%s",
                    (next_at, user.tenant_id, config["version"]),
                )
