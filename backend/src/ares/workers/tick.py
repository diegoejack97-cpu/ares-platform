# ruff: noqa: E501
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

from ares.agents.commercial_service import CommercialService
from ares.agents.runtime import AgentRuntime
from ares.config import get_settings
from ares.connectors.http_fake_crm import CRMProviderRequestError
from ares.connectors.provider import CRMProvider
from ares.connectors.resolver import TenantCRMProvider, crm_for
from ares.decision.execution_guard import ExecutionBlocked
from ares.decision.service import DecisionService
from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import PostgresEventJournal
from ares.integrations.service import IntegrationError, IntegrationService
from ares.intelligence.service import IntelligenceService
from ares.sentinels.service import SentinelService


@dataclass(frozen=True)
class TickResult:
    acquired: bool
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    sentinel_findings: int = 0


class TickWorker:
    """Claims durable jobs in short transactions and processes one bounded tick."""

    def __init__(
        self,
        database_url: str,
        supabase_url: str,
        supabase_secret_key: str,
        worker_name: str = "ares-api",
        provider: CRMProvider | None = None,
    ) -> None:
        self._database_url = database_url
        self._supabase_url = supabase_url.rstrip("/")
        self._supabase_secret_key = supabase_secret_key
        self._worker_name = worker_name
        self._provider = provider

    def run_once(
        self,
        batch_size: int = 10,
        job_kinds: list[str] | None = None,
        *,
        scan_sentinels: bool | None = None,
    ) -> TickResult:
        correlation_id = uuid4()
        with psycopg.connect(self._database_url, row_factory=dict_row) as lock_connection:
            lock_row = lock_connection.execute(
                "select pg_try_advisory_lock(hashtext('ares.tick.worker')) as acquired"
            ).fetchone()
            if lock_row is None:
                raise RuntimeError("advisory_lock_query_failed")
            acquired = bool(lock_row["acquired"])
            if not acquired:
                self._record_tick(correlation_id, acquired=False)
                return TickResult(acquired=False)

            try:
                jobs: list[dict[str, Any]] = []
                succeeded = 0
                failed = 0
                if batch_size > 0 and (job_kinds is None or "agent.execute" in job_kinds):
                    settings = get_settings()
                    runtime = AgentRuntime(
                        self._database_url,
                        model_id=settings.openai_model,
                        api_key=settings.openai_api_key.get_secret_value(),
                        worker_name=self._worker_name,
                        max_concurrent=settings.agent_max_concurrent_per_tenant,
                    )
                    # Reserve one turn before claiming legacy jobs, so a full
                    # projection queue cannot starve a five-minute agent chain.
                    receipt = runtime.process_next()
                    if receipt is not None:
                        succeeded += int(receipt.succeeded)
                        failed += int(not receipt.succeeded)
                        jobs.append({"kind": "agent.execute"})
                legacy_jobs = self._claim_jobs(max(0, batch_size - len(jobs)), job_kinds)
                jobs.extend(legacy_jobs)
                for job in legacy_jobs:
                    try:
                        self._process_job(job)
                    except Exception as error:  # noqa: BLE001 - durable failure boundary
                        self._fail_job(job, error)
                        failed += 1
                    else:
                        succeeded += 1
                should_scan = job_kinds is None if scan_sentinels is None else scan_sentinels
                findings = SentinelService(self._database_url).scan_sync() if should_scan else 0
                if should_scan:
                    settings = get_settings()
                    CommercialService(self._database_url, settings.openai_model).scan()
                    from ares.impact.evaluation import OutcomeService
                    from ares.knowledge.service import KnowledgeService

                    KnowledgeService(self._database_url).expire()
                    OutcomeService(self._database_url).scan()
                self._record_tick(
                    correlation_id,
                    acquired=True,
                    claimed=len(jobs),
                    succeeded=succeeded,
                    failed=failed,
                )
                return TickResult(True, len(jobs), succeeded, failed, findings)
            finally:
                lock_connection.execute("select pg_advisory_unlock(hashtext('ares.tick.worker'))")

    def _claim_jobs(
        self,
        batch_size: int,
        job_kinds: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                with claimable as (
                  select id
                  from public.jobs
                  where (status = 'queued' or (status='running' and lease_until < now()))
                    and kind <> 'agent.execute'
                    and run_after <= now()
                    and (%s::text[] is null or kind = any(%s::text[]))
                  order by run_after, created_at
                  for update skip locked
                  limit %s
                )
                update public.jobs job
                set status = 'running', attempts = attempts + 1,
                    lease_owner = %s, lease_until = now() + interval '2 minutes',
                    updated_at = now(), error_code = null
                from claimable
                where job.id = claimable.id
                returning job.*
                """,
                (job_kinds, job_kinds, batch_size, self._worker_name),
            ).fetchall()
        return [dict(row) for row in rows]

    def _process_job(self, job: dict[str, Any]) -> None:
        if job["kind"] in {"memory.index", "outcome.evaluate"}:
            from ares.impact.evaluation import OutcomeService
            from ares.knowledge.service import KnowledgeService

            settings = get_settings()
            payload = {**job["payload"], "recovered": job["attempts"] > 1}
            if job["kind"] == "memory.index":
                KnowledgeService(
                    self._database_url, settings.openai_api_key.get_secret_value()
                ).index(UUID(str(job["tenant_id"])), payload)
            else:
                OutcomeService(
                    self._database_url,
                    settings.openai_model,
                    settings.openai_api_key.get_secret_value(),
                ).process(UUID(str(job["tenant_id"])), payload)
            return
        if job["kind"] == "integration.sync":
            settings = get_settings()
            settings = settings.model_copy(update={"database_url": self._database_url})
            with crm_for(
                settings,
                UUID(str(job["tenant_id"])),
                UUID(str(job["payload"]["connection_id"])),
                str(job["correlation_id"]),
            ) as provider:
                IntegrationService(self._database_url, job["tenant_id"], provider).process_job(job)
            return
        elif job["kind"] == "commercial.analyze":
            settings = get_settings()
            CommercialService(
                self._database_url,
                settings.openai_model,
                settings.openai_api_key.get_secret_value(),
            ).process(
                UUID(str(job["tenant_id"])), {**job["payload"], "recovered": job["attempts"] > 1}
            )
        elif job["kind"] == "commercial.propose":
            from ares.auth.models import AuthenticatedUser
            from ares.decision.proposal_agents import decision_fingerprint_on

            tenant = UUID(str(job["tenant_id"]))
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                proposal = connection.execute(
                    "select * from public.commercial_proposals where tenant_id=%s and id=%s for update",
                    (tenant, job["payload"]["proposal_id"]),
                ).fetchone()
                if not proposal or proposal["status"] not in {"queued", "running"}:
                    return
                if proposal["status"] == "running":
                    connection.execute(
                        "update public.commercial_proposals set status='failed',error_code='proposal_outcome_unknown' where tenant_id=%s and id=%s",
                        (tenant, proposal["id"]),
                    )
                    return
                user = AuthenticatedUser(
                    tenant_id=tenant, user_id=proposal["actor_id"], role="admin"
                )
                role, config = CommercialService(self._database_url).config_on(
                    connection, user, execute=True
                )
                user = user.model_copy(update={"role": role})
                if (
                    not config
                    or not config["proactive_enabled"]
                    or not config["recommendations_enabled"]
                    or decision_fingerprint_on(connection, tenant, proposal["opportunity_id"])
                    != proposal["context_hash"]
                ):
                    raise ExecutionBlocked("proposal_context_stale")
                connection.execute(
                    "update public.commercial_proposals set status='running' where tenant_id=%s and id=%s",
                    (tenant, proposal["id"]),
                )
            settings = get_settings()
            proposal_provider = self._provider or TenantCRMProvider(
                settings.model_copy(update={"database_url": self._database_url}), tenant
            )
            try:
                result = DecisionService(
                    self._database_url,
                    tenant,
                    proposal_provider,
                    openai_api_key=settings.openai_api_key.get_secret_value(),
                    openai_model=settings.openai_model,
                ).create_recommendation_sync(proposal["opportunity_id"], str(user.user_id))
            except Exception:
                with psycopg.connect(self._database_url) as connection:
                    connection.execute(
                        "update public.commercial_proposals set status='failed',error_code='proposal_generation_failed' where tenant_id=%s and id=%s",
                        (tenant, proposal["id"]),
                    )
                raise
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    "update public.commercial_proposals set status='finished',recommendation_id=%s where tenant_id=%s and id=%s",
                    (result["recommendation_id"], tenant, proposal["id"]),
                )
        elif job["kind"] == "sentinel.interpret":
            from ares.sentinels.interpreter import SentinelInterpreter

            settings = get_settings()
            SentinelInterpreter(
                self._database_url,
                settings.openai_model,
                settings.openai_api_key.get_secret_value(),
            ).process(UUID(str(job["tenant_id"])), job["payload"])
        elif job["kind"] == "integration.project":
            IntelligenceService(self._database_url, job["tenant_id"]).process_event_sync(
                UUID(job["payload"]["event_id"])
            )
        elif job["kind"] == "action.execute":
            action_provider = self._provider or TenantCRMProvider(
                get_settings().model_copy(update={"database_url": self._database_url}),
                UUID(str(job["tenant_id"])),
            )
            intent_id = UUID(str(job["payload"]["intent_id"]))
            result = DecisionService(
                self._database_url, UUID(str(job["tenant_id"])), action_provider
            ).execute_intent_sync(intent_id)
            if result["status"] == "cancelled":
                raise ExecutionBlocked("action_intent_cancelled")
        elif job["kind"] == "webhook.normalize":
            receipt_id = UUID(str(job["payload"]["receipt_id"]))
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                receipt = connection.execute(
                    """
                select id, tenant_id, raw_payload_ref, correlation_id
                from public.webhook_receipts
                where id = %s and tenant_id = %s
                """,
                    (receipt_id, job["tenant_id"]),
                ).fetchone()
            if receipt is None:
                raise ValueError("receipt_not_found")
            raw_body = self._download_raw_payload(str(receipt["raw_payload_ref"]))
            incoming = IncomingCRMEvent.model_validate_json(raw_body)
            journal = PostgresEventJournal(self._database_url, receipt["tenant_id"])
            accepted = journal.record_sync(incoming, receipt["correlation_id"])
            intelligence = IntelligenceService(self._database_url, receipt["tenant_id"])
            intelligence.process_event_sync(accepted.event_id)
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                update public.webhook_receipts
                set status = 'processed', processed_at = now(), error_code = null
                where id = %s and tenant_id = %s
                """,
                    (receipt_id, job["tenant_id"]),
                )
        else:
            raise ValueError("unsupported_job_kind")
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                update public.jobs
                set status = 'succeeded', finished_at = now(), updated_at = now(),
                    lease_owner = null, lease_until = null, error_code = null
                where id = %s and tenant_id = %s
                """,
                (job["id"], job["tenant_id"]),
            )

    def _download_raw_payload(self, raw_payload_ref: str) -> bytes:
        if not self._supabase_secret_key:
            raise RuntimeError("supabase_secret_key_missing")
        bucket, separator, object_path = raw_payload_ref.partition("/")
        if not separator or bucket != "webhook-raw" or not object_path:
            raise ValueError("invalid_raw_payload_ref")
        response = httpx.get(
            f"{self._supabase_url}/storage/v1/object/authenticated/{bucket}/{object_path}",
            headers={
                "apikey": self._supabase_secret_key,
                "Authorization": f"Bearer {self._supabase_secret_key}",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.content

    def _fail_job(self, job: dict[str, Any], error: Exception) -> None:
        if job["kind"] == "integration.sync":
            self._fail_integration(job, error)
            return
        blocked = isinstance(error, ExecutionBlocked)
        terminal = blocked or int(job["attempts"]) >= 3
        error_code = (
            error.code if isinstance(error, ExecutionBlocked) else type(error).__name__[:80]
        )
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                update public.jobs
                set status = %s::public.job_status,
                    run_after = case when %s then run_after else now() + interval '1 minute' end,
                    finished_at = case when %s then now() else null end,
                    updated_at = now(), lease_owner = null, lease_until = null,
                    error_code = %s
                where id = %s and tenant_id = %s
                """,
                (
                    "failed" if blocked else "dead_letter" if terminal else "queued",
                    terminal,
                    terminal,
                    error_code,
                    job["id"],
                    job["tenant_id"],
                ),
            )
            connection.execute(
                """
                insert into public.event_failures (
                  tenant_id, job_id, category, redacted_detail, correlation_id
                ) values (%s, %s, 'worker_processing', %s, %s)
                """,
                (job["tenant_id"], job["id"], error_code, job["correlation_id"]),
            )

    def _fail_integration(self, job: dict[str, Any], error: Exception) -> None:
        code = str(getattr(error, "code", type(error).__name__))[:80]
        restart = code in {"snapshot_expired", "invalid_cursor", "cursor_filter_mismatch"}
        terminal = int(job["attempts"]) >= 5 or isinstance(error, (IntegrationError, ValueError))
        if isinstance(error, CRMProviderRequestError) and error.status_code in {401, 403, 404}:
            terminal = True
        delay = min(300, 2 ** min(int(job["attempts"]), 8))
        if isinstance(error, CRMProviderRequestError) and error.retry_after:
            with suppress(ValueError):
                delay = max(delay, min(3600, int(error.retry_after)))
        with psycopg.connect(self._database_url) as connection:
            if restart:
                # Restart from the run's fixed window. Dedupe/version checks make replay safe.
                connection.execute(
                    "update public.jobs set payload=jsonb_set(jsonb_set(payload,'{cursor}',"
                    "'null'::jsonb),'{pages}','0'::jsonb) where tenant_id=%s and id=%s",
                    (job["tenant_id"], job["id"]),
                )
            connection.execute(
                "update public.jobs set status=%s,error_code=%s,lease_owner=null,lease_until=null,"
                "run_after=now()+(%s * interval '1 second'),updated_at=now(),"
                "finished_at=case when %s then now() else null end where tenant_id=%s and id=%s",
                (
                    "dead_letter" if terminal else "queued",
                    code,
                    delay,
                    terminal,
                    job["tenant_id"],
                    job["id"],
                ),
            )
            connection.execute(
                "update public.connections set status='degraded',updated_at=now() "
                "where tenant_id=%s and id=%s and status<>'revoked'",
                (job["tenant_id"], job["payload"]["connection_id"]),
            )
            connection.execute(
                "insert into public.event_failures(tenant_id,job_id,category,redacted_detail,"
                "correlation_id) values(%s,%s,'integration_sync',%s,%s)",
                (job["tenant_id"], job["id"], code, job["correlation_id"]),
            )

    def _record_tick(
        self,
        correlation_id: UUID,
        *,
        acquired: bool,
        claimed: int = 0,
        succeeded: int = 0,
        failed: int = 0,
    ) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                insert into public.worker_ticks (
                  worker_name, acquired, claimed_count, succeeded_count,
                  failed_count, finished_at, correlation_id
                ) values (%s, %s, %s, %s, %s, now(), %s)
                """,
                (
                    self._worker_name,
                    acquired,
                    claimed,
                    succeeded,
                    failed,
                    correlation_id,
                ),
            )
