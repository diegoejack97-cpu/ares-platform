from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

from ares.config import get_settings
from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.connectors.provider import CRMProvider
from ares.decision.service import DecisionService
from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import PostgresEventJournal
from ares.integrations.service import IntegrationError, IntegrationService
from ares.intelligence.service import IntelligenceService


@dataclass(frozen=True)
class TickResult:
    acquired: bool
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0


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

    def run_once(self, batch_size: int = 10, job_kinds: list[str] | None = None) -> TickResult:
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
                jobs = self._claim_jobs(batch_size, job_kinds)
                succeeded = 0
                failed = 0
                for job in jobs:
                    try:
                        self._process_job(job)
                    except Exception as error:  # noqa: BLE001 - durable failure boundary
                        self._fail_job(job, error)
                        failed += 1
                    else:
                        succeeded += 1
                self._record_tick(
                    correlation_id,
                    acquired=True,
                    claimed=len(jobs),
                    succeeded=succeeded,
                    failed=failed,
                )
                return TickResult(True, len(jobs), succeeded, failed)
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
        if job["kind"] == "integration.sync":
            settings = get_settings()
            if settings.environment != "development":
                raise IntegrationError("client_crm_adapter_not_configured", 503)
            provider = FakeCRMHTTPProvider(
                settings.fake_crm_base_url,
                settings.fake_crm_api_key.get_secret_value(),
                settings.fake_crm_timeout_seconds,
                correlation_id=str(job["correlation_id"]),
            )
            try:
                IntegrationService(self._database_url, job["tenant_id"], provider).process_job(job)
            finally:
                provider.close()
            return
        elif job["kind"] == "integration.project":
            IntelligenceService(self._database_url, job["tenant_id"]).process_event_sync(
                UUID(job["payload"]["event_id"])
            )
        elif job["kind"] == "action.execute":
            if self._provider is None:
                raise RuntimeError("crm_provider_missing")
            intent_id = UUID(str(job["payload"]["intent_id"]))
            DecisionService(
                self._database_url, UUID(str(job["tenant_id"])), self._provider
            ).execute_intent_sync(intent_id)
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
        terminal = int(job["attempts"]) >= 3
        error_code = type(error).__name__[:80]
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
                    "dead_letter" if terminal else "queued",
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
