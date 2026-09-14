from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser


class AgentAccessDenied(Exception):
    pass


class AgentTransparencyService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @contextmanager
    def db(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute("set transaction isolation level repeatable read, read only")
            connection.execute("set local statement_timeout = '5s'")
            yield connection

    def summary(self, user: AuthenticatedUser, days: int = 30) -> dict[str, Any]:
        if user.role not in {"admin", "manager", "auditor"}:
            raise AgentAccessDenied
        if not 1 <= days <= 90:
            raise ValueError("invalid_window")
        until = datetime.now(UTC)
        since = until - timedelta(days=days)
        with self.db() as db:
            # Recheck access in the same snapshot used for metrics, including suspension.
            access = db.execute(
                """
                select 1 from public.memberships m
                join public.tenants t on t.id = m.tenant_id
                where m.tenant_id = %s and m.user_id = %s and m.active
                  and m.role in ('admin', 'manager', 'auditor') and t.status = 'active'
                  and exists (
                    select 1 from public.tenant_entitlements e
                    where e.tenant_id = m.tenant_id and e.module = 'ares_connect'
                      and e.status = 'active'
                      and (e.expires_at is null or e.expires_at > now())
                  )
                """,
                (user.tenant_id, user.user_id),
            ).fetchone()
            if access is None:
                raise AgentAccessDenied
            rows = db.execute(
                """
                select agent_name, agent_version, generation_mode, model_id,
                  count(*) as runs,
                  count(*) filter (where status = 'running') as running,
                  count(*) filter (where status = 'succeeded') as succeeded,
                  count(*) filter (where status = 'degraded') as degraded,
                  count(*) filter (where status = 'failed') as failed,
                  count(*) filter (where finished_at >= started_at
                    and status <> 'running') as latency_samples,
                  percentile_cont(0.95) within group
                    (order by extract(epoch from (finished_at - started_at)) * 1000)
                    filter (where finished_at >= started_at
                      and status <> 'running') as latency_p95_ms,
                  max(started_at) as last_run_at,
                  count(*) filter (where usage_status='observed') as usage_samples,
                  count(measured_cost) as cost_samples,
                  count(*) filter (where usage_status='not_called') as not_called,
                  sum(measured_input) as input_tokens,
                  sum(measured_output) as output_tokens,
                  sum(measured_cost) as cost_usd
                from public.agent_runs r
                left join lateral (
                  select u.status as usage_status, u.input_tokens as measured_input,
                    u.output_tokens as measured_output, u.cost_usd as measured_cost
                  from public.model_usage u where u.tenant_id=r.tenant_id and u.run_id=r.id
                ) usage on true
                where tenant_id = %s and started_at >= %s and started_at < %s
                group by agent_name, agent_version, generation_mode, model_id
                order by agent_name, agent_version, generation_mode, model_id nulls last
                """,
                (user.tenant_id, since, until),
            ).fetchall()
        return {
            "items": [
                {
                    **dict(row),
                    "cost_status": (
                        "calculated"
                        if row["cost_samples"] + row["not_called"] == row["runs"]
                        and row["cost_samples"]
                        else "partial"
                        if row["cost_samples"]
                        else "not_instrumented"
                    ),
                    "autonomy": "read_only" if row["agent_name"] == "chat" else "proposal_only",
                }
                for row in rows
            ],
            "window": {"since": since, "until": until, "days": days},
            "source": "agent_runs",
            "freshness_at": until,
            "latency_definition": "run_wall_time_ms",
            "limitations": [
                "Cost uses observed tokens and a versioned tariff, not an invoice; "
                "missing runs are excluded.",
                "Latency covers the recorded run, not only the model request.",
                "Follow-up and triage share a run; no separate triage metrics are inferred.",
                "Autonomy describes proposal generation; Policy and worker govern execution.",
            ],
        }
