"""Real PostgreSQL acceptance: fencing, handoffs, quotas and revoked authority."""
# SQL statements remain complete for audit review.
# ruff: noqa: E501

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.agents.catalog import CATALOG, SEQUENCE
from ares.agents.contracts import AnalysisOutput, RoutineCommand, StartAnalysis
from ares.agents.executor import AgentOutcome, AgnoExecutor
from ares.agents.runtime import AgentRuntime, AgentRuntimeError, LeaseLost
from ares.ai.usage import UsageObservation
from ares.auth.models import AuthenticatedUser

URL = os.getenv("ARES_TEST_DATABASE_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not URL, reason="Postgres required")]


class SyntheticExecutor:
    def __init__(self):
        self.calls = []
        self.invalid_evidence = False
        self.fail = False

    async def execute(self, definition, payload, model_id):
        self.calls.append((definition.agent_id, payload))
        if self.fail:
            raise RuntimeError("private model error")
        return AgentOutcome(
            AnalysisOutput(
                summary="Synthetic verified context",
                evidence_refs=["invented"] if self.invalid_evidence else payload.evidence_refs,
                limitations=[],
                needs_human_review=True,
            ),
            UsageObservation("observed", model_id, 100, 10, 0, Decimal("0.001"), "synthetic-test"),
        )


@pytest.fixture
def fixture():
    assert URL
    tenant, actor, seller, opportunity, snapshot, event = [uuid4() for _ in range(6)]
    with psycopg.connect(URL) as db:
        db.execute("insert into auth.users(id) values(%s),(%s)", (actor, seller))
        db.execute(
            "insert into public.tenants(id,name,slug) values(%s,'Synthetic agent execution',%s)",
            (tenant, str(tenant)),
        )
        db.execute(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) values(%s,'ares_connect','active',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.tenant_billing_state(tenant_id,state,reason,changed_by) values(%s,'active','synthetic contract',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.tenant_quotas(tenant_id,seats_limit,agent_slots,sentinel_slots,ai_daily_budget_brl,ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) values(%s,10,2,2,50,500,5,'synthetic test',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'admin'),(%s,%s,'seller')",
            (tenant, actor, tenant, seller),
        )
        db.execute(
            "insert into public.ares_opportunities(id,tenant_id,opportunity_type,state,owner_user_id) values(%s,%s,'revenue_recovery','prioritized',%s)",
            (opportunity, tenant, actor),
        )
        db.execute(
            "insert into public.context_snapshots(id,tenant_id,opportunity_id,snapshot_version,opportunity_state,content_hash,source,facts_json,citations_json) values(%s,%s,%s,1,'prioritized','synthetic','ares',%s,%s)",
            (
                snapshot,
                tenant,
                opportunity,
                Jsonb(
                    {
                        "deal": {"title": "Synthetic deal", "value": 0},
                        "events": [
                            {
                                "id": str(event),
                                "event_type": "deal.updated",
                                "data": {"stage": "proposal"},
                            }
                        ],
                    }
                ),
                Jsonb([{"event_id": str(event)}]),
            ),
        )
    user = AuthenticatedUser(user_id=actor, tenant_id=tenant, role="admin")
    executor = SyntheticExecutor()
    runtime = AgentRuntime(URL, executor=executor)
    runtime.configure(
        user, RoutineCommand(enabled=True, expected_version=0, reason="Synthetic activation")
    )
    yield runtime, user, opportunity, snapshot, executor, seller
    with psycopg.connect(URL) as db:
        db.execute(
            "update public.agent_workflows set root_run_id=null where tenant_id=%s", (tenant,)
        )
        db.execute("update public.agent_runs set parent_run_id=null where tenant_id=%s", (tenant,))
        for table in [
            "agent_handoffs",
            "jobs",
            "model_usage",
            "ai_usage_ledger",
            "ai_budget_reservations",
            "agent_runs",
            "agent_workflows",
            "agent_routines",
            "audit_log",
            "tenant_usage_daily",
            "context_snapshots",
            "ares_opportunities",
            "sentinel_scan_runs",
            "sentinel_schedule_audit",
            "sentinel_schedules",
            "memberships",
            "tenant_entitlements",
            "tenant_billing_state",
            "tenant_quotas",
        ]:
            # Static table identifiers, no user data interpolation.
            db.execute(f"delete from public.{table} where tenant_id=%s", (tenant,))
        db.execute("delete from public.tenants where id=%s", (tenant,))
        db.execute("delete from auth.users where id in (%s,%s)", (actor, seller))


def start(fixture, key=None):
    runtime, user, opportunity, snapshot, _, _ = fixture
    return runtime.start(
        user,
        StartAnalysis(
            opportunity_id=opportunity, context_ref=snapshot, idempotency_key=key or uuid4()
        ),
    )


def query(fixture, statement, params=()):
    with psycopg.connect(URL, row_factory=dict_row) as db:
        cursor = db.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def test_two_distinct_agents_share_chain_and_usage_ledger(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    assert runtime.process_next() and runtime.process_next()
    result = runtime.get(user, chain["id"])
    assert result["status"] == "succeeded"
    assert [r["agent_name"] for r in result["runs"]] == list(SEQUENCE)
    assert result["runs"][1]["parent_run_id"] == result["runs"][0]["id"] == result["root_run_id"]
    assert len(result["handoffs"]) == 1
    assert executor.calls[1][1].previous == AnalysisOutput.model_validate(
        result["runs"][0]["output_json"]
    )
    assert (
        len(
            query(fixture, "select * from public.model_usage where tenant_id=%s", (user.tenant_id,))
        )
        == 2
    )
    assert (
        len(
            query(
                fixture,
                "select * from public.ai_usage_ledger where tenant_id=%s",
                (user.tenant_id,),
            )
        )
        == 2
    )
    assert not runtime.process_next()


def test_repeated_and_concurrent_requests_create_one_job(fixture):
    key = uuid4()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: start(fixture, key), range(4)))
    assert len({r["id"] for r in results}) == 1
    runtime, user, _, _, _, _ = fixture
    assert (
        len(
            query(
                fixture,
                "select id from public.jobs where tenant_id=%s and kind='agent.execute'",
                (user.tenant_id,),
            )
        )
        == 1
    )
    with pytest.raises(AgentRuntimeError, match="agent_idempotency_conflict"):
        runtime.start(
            user, StartAnalysis(opportunity_id=fixture[2], context_ref=uuid4(), idempotency_key=key)
        )


@pytest.mark.parametrize(
    "change,code",
    [
        ("update public.memberships set active=false where tenant_id=%s", "agent_access_denied"),
        (
            "update public.tenant_billing_state set state='degraded',due_since=current_date-2,grace_until=current_date-1 where tenant_id=%s",
            "billing_degraded",
        ),
        (
            "update public.tenant_quotas set agent_slots=1 where tenant_id=%s",
            "agent_routine_unavailable",
        ),
        (
            "update public.tenant_quotas set ai_daily_budget_brl=0 where tenant_id=%s",
            "ai_budget_exceeded",
        ),
        (
            "update public.agent_routines set enabled=false where tenant_id=%s",
            "agent_routine_unavailable",
        ),
    ],
)
def test_revocation_and_quota_prevent_the_next_agent(fixture, change, code):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    runtime.process_next()
    query(fixture, change, (user.tenant_id,))
    runtime.process_next()
    assert len(executor.calls) == 1
    row = query(
        fixture, "select status,error_code from public.agent_workflows where id=%s", (chain["id"],)
    )[0]
    assert row == {"status": "blocked", "error_code": code}


def test_owner_scope_and_cross_tenant_context_cannot_be_bypassed(fixture):
    runtime, user, opportunity, snapshot, _, seller = fixture
    impersonated = user.model_copy(update={"user_id": seller})  # claims say admin; DB says seller
    with pytest.raises(AgentRuntimeError, match="agent_scope_denied"):
        runtime.start(
            impersonated,
            StartAnalysis(
                opportunity_id=opportunity, context_ref=snapshot, idempotency_key=uuid4()
            ),
        )
    chain = start(fixture)
    with pytest.raises(AgentRuntimeError):
        runtime.get(user.model_copy(update={"tenant_id": uuid4()}), chain["id"])
    with pytest.raises(AgentRuntimeError):
        runtime.get(user.model_copy(update={"user_id": seller}), chain["id"])
    with pytest.raises(AgentRuntimeError, match="agent_context_stale_or_missing"):
        runtime.start(
            user,
            StartAnalysis(opportunity_id=opportunity, context_ref=uuid4(), idempotency_key=uuid4()),
        )


def test_cancel_before_dispatch_releases_budget_and_fences_old_worker(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    claimed = runtime._claim()
    run, _ = runtime._prepare(claimed)
    runtime.cancel(user, chain["id"])
    with pytest.raises(LeaseLost):
        runtime._dispatch(claimed, run)
    assert not executor.calls
    assert (
        query(fixture, "select status from public.ai_budget_reservations where run_id=%s", (run,))[
            0
        ]["status"]
        == "released"
    )
    assert runtime.get(user, chain["id"])["status"] == "cancelled"


def test_restart_before_dispatch_retries_with_new_fence(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    old = runtime._claim()
    run, _ = runtime._prepare(old)
    query(
        fixture,
        "update public.jobs set lease_until=now()-interval '1 second' where id=%s",
        (old["id"],),
    )
    assert runtime.recover() == 1
    assert runtime.process_next() and runtime.process_next()
    assert runtime.get(user, chain["id"])["status"] == "succeeded"
    assert len(executor.calls) == 2
    assert (
        query(fixture, "select status from public.ai_budget_reservations where run_id=%s", (run,))[
            0
        ]["status"]
        == "released"
    )
    with pytest.raises(LeaseLost):
        runtime._dispatch(old, run)


def test_restart_after_dispatch_does_not_rebill_or_resend(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    old = runtime._claim()
    run, _ = runtime._prepare(old)
    runtime._dispatch(old, run)
    query(
        fixture,
        "update public.jobs set lease_until=now()-interval '1 second' where id=%s",
        (old["id"],),
    )
    runtime.recover()
    assert runtime.get(user, chain["id"])["error_code"] == "agent_model_result_unknown"
    assert not runtime.process_next() and not executor.calls
    assert (
        query(fixture, "select status from public.ai_budget_reservations where run_id=%s", (run,))[
            0
        ]["status"]
        == "reserved"
    )


def test_concurrent_claim_respects_shared_tenant_limit(fixture):
    runtime = fixture[0]
    for _ in range(4):
        start(fixture)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: runtime._claim(), range(4)))
    # SKIP LOCKED may return idle before another admission transaction commits.
    admitted = sum(job is not None for job in claimed)
    assert 1 <= admitted <= 2
    while runtime._claim() is not None:
        admitted += 1
    assert admitted == 2


def test_invalid_evidence_is_not_published(fixture):
    runtime, user, _, _, executor, _ = fixture
    executor.invalid_evidence = True
    chain = start(fixture)
    runtime.process_next()
    result = runtime.get(user, chain["id"])
    assert result["error_code"] == "agent_evidence_invalid"
    assert all(r["output_json"] is None for r in result["runs"])
    assert len(executor.calls) == 1


def test_chain_cost_limit_is_checked_before_model(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    query(
        fixture,
        "update public.agent_workflows set budget_limit_usd=0.000001 where id=%s",
        (chain["id"],),
    )
    runtime.process_next()
    assert not executor.calls
    assert runtime.get(user, chain["id"])["error_code"] == "agent_chain_budget_exceeded"


def test_unconfigured_model_is_explicitly_degraded(fixture):
    runtime, user, _, _, _, _ = fixture
    runtime.executor = AgnoExecutor("")
    chain = start(fixture)
    runtime.process_next()
    runtime.process_next()
    result = runtime.get(user, chain["id"])
    assert result["status"] == "degraded"
    assert all(r["status"] == "degraded" for r in result["runs"])
    assert not query(
        fixture, "select id from public.ai_usage_ledger where tenant_id=%s", (user.tenant_id,)
    )


def test_admin_configuration_version_and_plan_capacity(fixture):
    runtime, user, _, _, _, seller = fixture
    with pytest.raises(AgentRuntimeError, match="agent_admin_required"):
        runtime.configure(
            user.model_copy(update={"user_id": seller}),
            RoutineCommand(enabled=False, expected_version=1, reason="Synthetic pause"),
        )
    with pytest.raises(AgentRuntimeError, match="agent_routine_version_conflict"):
        runtime.configure(
            user, RoutineCommand(enabled=False, expected_version=0, reason="Synthetic pause")
        )
    runtime.configure(
        user, RoutineCommand(enabled=False, expected_version=1, reason="Synthetic pause")
    )
    query(
        fixture,
        "update public.tenant_quotas set agent_slots=1 where tenant_id=%s",
        (user.tenant_id,),
    )
    with pytest.raises(AgentRuntimeError, match="agent_capacity_unavailable"):
        runtime.configure(
            user, RoutineCommand(enabled=True, expected_version=2, reason="Synthetic activation")
        )


def test_timeout_does_not_loop_or_enqueue_child(fixture, monkeypatch):
    import ares.agents.runtime as module

    runtime, user, _, _, _, _ = fixture

    class SlowExecutor:
        async def execute(self, *args):
            await asyncio.sleep(1)

    runtime.executor = SlowExecutor()
    monkeypatch.setattr(
        module,
        "CATALOG",
        {**CATALOG, SEQUENCE[0]: replace(CATALOG[SEQUENCE[0]], timeout_seconds=0.01)},
    )
    chain = start(fixture)
    runtime.process_next()
    assert runtime.get(user, chain["id"])["error_code"] == "agent_timeout"
    assert not runtime.process_next()


def test_dispatch_failure_retains_reserve_without_logging_exception(fixture):
    runtime, user, _, _, executor, _ = fixture
    executor.fail = True
    chain = start(fixture)
    runtime.process_next()
    result = runtime.get(user, chain["id"])
    assert result["error_code"] == "agent_model_result_unknown"
    assert "private" not in str(result)
    assert not runtime.process_next()


def test_tables_are_not_readable_directly_by_browser_role(fixture):
    with psycopg.connect(URL) as db:
        for name in ("agent_routines", "agent_workflows", "agent_handoffs"):
            assert not db.execute(
                "select has_table_privilege('authenticated',%s,'SELECT')", (f"public.{name}",)
            ).fetchone()[0]


def test_cancel_during_model_call_keeps_usage_but_discards_output(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)

    class CancellingExecutor:
        async def execute(self, *args):
            runtime.cancel(user, chain["id"])
            return await executor.execute(*args)

    runtime.executor = CancellingExecutor()
    runtime.process_next()
    result = runtime.get(user, chain["id"])
    assert result["status"] == "cancelled"
    assert all(run["output_json"] is None for run in result["runs"])
    assert not result["handoffs"]
    assert (
        len(
            query(
                fixture, "select id from public.model_usage where tenant_id=%s", (user.tenant_id,)
            )
        )
        == 1
    )
    assert not runtime.process_next()


def test_revoked_access_during_dispatch_prevents_result_publication(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)

    class RevokingExecutor:
        async def execute(self, *args):
            query(
                fixture,
                "update public.tenant_quotas set agent_slots=0 where tenant_id=%s",
                (user.tenant_id,),
            )
            return await executor.execute(*args)

    runtime.executor = RevokingExecutor()
    runtime.process_next()
    result = runtime.get(user, chain["id"])
    assert result["status"] == "blocked"
    assert all(run["output_json"] is None for run in result["runs"])
    assert not result["handoffs"]


def test_loop_payload_is_rejected_before_execution(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    runtime.process_next()
    query(
        fixture,
        "update public.jobs set payload=jsonb_set(payload,'{agent_id}','\"context-triage\"') where tenant_id=%s and kind='agent.execute' and status='queued'",
        (user.tenant_id,),
    )
    runtime.process_next()
    assert runtime.get(user, chain["id"])["error_code"] == "agent_contract_invalid"
    assert len(executor.calls) == 1


def test_heartbeat_cannot_resurrect_expired_lease(fixture):
    runtime = fixture[0]
    start(fixture)
    claimed = runtime._claim()
    assert runtime._heartbeat(claimed)
    query(
        fixture,
        "update public.jobs set lease_until=now()-interval '1 second' where id=%s",
        (claimed["id"],),
    )
    assert not runtime._heartbeat(claimed)


def test_new_snapshot_invalidates_queued_analysis(fixture):
    runtime, user, opportunity, _, executor, _ = fixture
    chain = start(fixture)
    query(
        fixture,
        "insert into public.context_snapshots(tenant_id,opportunity_id,snapshot_version,opportunity_state,content_hash,source) values(%s,%s,2,'prioritized','new','ares')",
        (user.tenant_id, opportunity),
    )
    runtime.process_next()
    assert not executor.calls
    assert runtime.get(user, chain["id"])["error_code"] == "agent_context_stale_or_missing"


def test_catalog_change_blocks_pending_workflow(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    query(
        fixture,
        "update public.agent_workflows set definition_hash='outdated' where id=%s",
        (chain["id"],),
    )
    runtime.process_next()
    assert not executor.calls
    assert runtime.get(user, chain["id"])["error_code"] == "agent_definition_unavailable"


def test_workflow_deadline_ends_queued_chain(fixture):
    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    query(
        fixture,
        "update public.agent_workflows set deadline_at=now()-interval '1 second' where id=%s",
        (chain["id"],),
    )
    runtime.recover()
    assert not runtime.process_next() and not executor.calls
    assert runtime.get(user, chain["id"])["error_code"] == "agent_chain_timeout"


def test_control_api_uses_real_persistence_and_async_receipt(fixture):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ares.agents.runtime_api import agent_runtime_router
    from ares.config import Settings

    runtime, user, opportunity, snapshot, _, _ = fixture
    server = FastAPI()
    server.include_router(
        agent_runtime_router(Settings(_env_file=None, database_url=URL), lambda: user)
    )
    client = TestClient(server)
    assert client.get("/api/v1/agents/catalog").json()["agent_slots"] == 2
    response = client.post(
        "/api/v1/agents/workflows",
        json={
            "opportunity_id": str(opportunity),
            "context_ref": str(snapshot),
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 202
    assert response.headers["Cache-Control"] == "no-store"
    workflow_id = response.json()["id"]
    assert client.get(f"/api/v1/agents/workflows/{workflow_id}").json()["status"] == "queued"
    assert (
        client.post(f"/api/v1/agents/workflows/{workflow_id}/cancel").json()["status"]
        == "cancelled"
    )


def test_tick_dispatches_new_job_without_crm_action(fixture, monkeypatch):
    import ares.workers.tick as module
    from ares.workers.tick import TickWorker

    runtime, user, _, _, executor, _ = fixture
    chain = start(fixture)
    monkeypatch.setattr(module, "AgentRuntime", lambda *args, **kwargs: runtime)
    tick = TickWorker(URL, "http://127.0.0.1:55421", "")
    assert tick.run_once(job_kinds=["agent.execute"], scan_sentinels=False).claimed == 1
    assert tick.run_once(job_kinds=["agent.execute"], scan_sentinels=False).claimed == 1
    assert runtime.get(user, chain["id"])["status"] == "succeeded"
    assert len(executor.calls) == 2


def test_agent_turn_is_not_starved_by_a_full_legacy_queue(fixture, monkeypatch):
    import ares.workers.tick as module
    from ares.workers.tick import TickWorker

    runtime, _, _, _, executor, _ = fixture
    start(fixture)
    monkeypatch.setattr(module, "AgentRuntime", lambda *args, **kwargs: runtime)
    tick = TickWorker(URL, "http://127.0.0.1", "synthetic-test-key")
    claim_sizes = []

    def legacy_queue(batch_size, _kinds):
        claim_sizes.append(batch_size)
        return [{"kind": "synthetic"} for _ in range(batch_size)]

    monkeypatch.setattr(tick, "_claim_jobs", legacy_queue)
    monkeypatch.setattr(tick, "_process_job", lambda _: None)
    result = tick.run_once(batch_size=1, scan_sentinels=False)
    assert len(executor.calls) == 1
    assert claim_sizes == [0]
    assert result.claimed == result.succeeded == 1 and result.failed == 0
