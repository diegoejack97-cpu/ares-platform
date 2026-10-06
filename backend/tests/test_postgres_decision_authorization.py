"""Persisted roles and contracts must still authorize queued CRM writes at dispatch."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Event
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser
from ares.connectors.fake_crm import FakeCRMProvider
from ares.connectors.models import CRMCapabilities, CRMWriteResult
from ares.decision.authorization import DecisionAuthorizationError
from ares.decision.execution_guard import ExecutionBlocked, check_execution_contract
from ares.decision.models import ActionDraft, DecideCommand
from ares.decision.policy import PolicyEngine, PolicyResult
from ares.decision.service import DecisionConflict, DecisionService
from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import PostgresEventJournal
from ares.intelligence.service import IntelligenceService
from ares.workers.tick import TickWorker

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")
TENANT = UUID("20000000-0000-0000-0000-000000000001")
ADMIN = "10000000-0000-0000-0000-000000000001"
MANAGER = "10000000-0000-0000-0000-000000000003"
SELLER = "10000000-0000-0000-0000-000000000004"
AUDITOR = "10000000-0000-0000-0000-000000000005"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL required"),
]


class CountingProvider(FakeCRMProvider):
    def __init__(self) -> None:
        super().__init__("synthetic-regression")
        self.write_calls = 0
        self.task_enabled = True

    def capabilities(self) -> CRMCapabilities:
        return CRMCapabilities(create_task=self.task_enabled)

    def create_task(self, deal_id: str, title: str, idempotency_key: str) -> CRMWriteResult:
        self.write_calls += 1
        return super().create_task(deal_id, title, idempotency_key)


class AdminOnlyTaskPolicy(PolicyEngine):
    def evaluate(self, action: ActionDraft, capabilities: CRMCapabilities) -> PolicyResult:
        result = super().evaluate(action, capabilities)
        return replace(result, policy_version=result.policy_version + 1, required_role="admin")


@pytest.fixture
def db_url() -> str:
    assert DATABASE_URL is not None
    return DATABASE_URL


@pytest.fixture
def opportunity(db_url: str) -> tuple[DecisionService, CountingProvider, UUID]:
    now = datetime.now(UTC)
    journal = PostgresEventJournal(db_url, TENANT)
    accepted = journal.record_sync(
        IncomingCRMEvent(
            provider_event_id=f"authorization-{uuid4()}",
            event_type="deal.updated",
            aggregate_type="deal",
            aggregate_id=f"deal-authorization-{uuid4().hex[:8]}",
            occurred_at=now,
            data={
                "title": "Synthetic authorization regression",
                "stage": "proposal",
                "risk": "follow_up_overdue",
                "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
                "days_in_stage": 9,
                "next_step": None,
                "value": 42000,
                "currency": "BRL",
            },
        )
    )
    pipeline = IntelligenceService(db_url, TENANT).process_event_sync(accepted.event_id)
    assert pipeline.opportunity_id is not None
    provider = CountingProvider()
    return DecisionService(db_url, TENANT, provider), provider, pipeline.opportunity_id


@contextmanager
def changed_row(
    db_url: str, table: str, key: str, target: Any, changes: dict[str, Any]
) -> Iterator[None]:
    """Restore shared fixture settings even when the regression assertion fails."""
    fields = list(changes)
    query = sql.SQL("update {} set {} where {}=%s").format(
        sql.Identifier("public", table),
        sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(field)) for field in fields),
        sql.Identifier(key),
    )
    with psycopg.connect(db_url, row_factory=dict_row) as db:
        original = db.execute(
            sql.SQL("select * from {} where {}=%s").format(
                sql.Identifier("public", table), sql.Identifier(key)
            ),
            (target,),
        ).fetchone()
        assert original is not None
        db.execute(query, [changes[field] for field in fields] + [target])
    try:
        yield
    finally:
        with psycopg.connect(db_url) as db:
            db.execute(query, [original[field] for field in fields] + [target])


@pytest.fixture
def foreign_actor(db_url: str) -> Iterator[str]:
    actor, tenant = uuid4(), uuid4()
    with psycopg.connect(db_url) as db:
        db.execute("insert into auth.users(id) values(%s)", (actor,))
        db.execute(
            "insert into public.tenants(id,name,slug) values(%s,'Synthetic other company',%s)",
            (tenant, f"other-{tenant}"),
        )
        db.execute(
            "insert into public.tenant_quotas(tenant_id,seats_limit,ai_daily_budget_brl,"
            "ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) "
            "values(%s,1,0,0,1,'synthetic regression',%s)",
            (tenant, actor),
        )
        db.execute(
            "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'admin')",
            (tenant, actor),
        )
    try:
        yield str(actor)
    finally:
        with psycopg.connect(db_url) as db:
            db.execute("delete from public.memberships where tenant_id=%s", (tenant,))
            db.execute("delete from public.tenant_quotas where tenant_id=%s", (tenant,))
            db.execute("delete from public.sentinel_schedules where tenant_id=%s", (tenant,))
            db.execute("delete from public.tenants where id=%s", (tenant,))
            db.execute("delete from auth.users where id=%s", (actor,))


def counts(db_url: str, opportunity_id: UUID) -> tuple[int, ...]:
    with psycopg.connect(db_url) as db:
        row = db.execute(
            "select (select count(*) from public.recommendations where opportunity_id=%s),"
            "(select count(*) from public.agent_runs where opportunity_id=%s),"
            "(select count(*) from public.ares_interventions where opportunity_id=%s)",
            (opportunity_id, opportunity_id, opportunity_id),
        ).fetchone()
    assert row is not None
    return row


def pending_state(db_url: str, recommendation_id: UUID) -> tuple[Any, ...]:
    with psycopg.connect(db_url) as db:
        row = db.execute(
            "select r.status,r.version,a.status,"
            "(select count(*) from public.decisions where recommendation_id=r.id),"
            "(select count(*) from public.action_intents where recommendation_id=r.id) "
            "from public.recommendations r join public.approval_requests a "
            "on a.recommendation_id=r.id where r.id=%s",
            (recommendation_id,),
        ).fetchone()
    assert row is not None
    return row


@pytest.mark.parametrize("actor", [AUDITOR, SELLER, "not-a-user"])
def test_recommendation_request_denial_has_no_durable_effects(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID], actor: str
) -> None:
    service, provider, opportunity_id = opportunity
    before = counts(db_url, opportunity_id)
    assert service._can_request_recommendation_sync(opportunity_id, actor) is False
    with pytest.raises(DecisionAuthorizationError):
        service.create_recommendation_sync(opportunity_id, actor)
    assert counts(db_url, opportunity_id) == before
    assert provider.write_calls == 0


def test_other_company_admin_cannot_request_or_decide(
    db_url: str,
    opportunity: tuple[DecisionService, CountingProvider, UUID],
    foreign_actor: str,
) -> None:
    service, provider, opportunity_id = opportunity
    before = counts(db_url, opportunity_id)
    with pytest.raises(DecisionAuthorizationError):
        service.create_recommendation_sync(opportunity_id, foreign_actor)
    assert counts(db_url, opportunity_id) == before
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    snapshot = pending_state(db_url, created["recommendation_id"])
    with pytest.raises(DecisionAuthorizationError):
        service.decide_sync(
            created["recommendation_id"],
            DecideCommand(verdict="approved", expected_version=created["version"]),
            foreign_actor,
        )
    assert pending_state(db_url, created["recommendation_id"]) == snapshot
    assert provider.write_calls == 0


@pytest.mark.parametrize("change", [{"active": False}, {"role": "auditor"}])
def test_inactive_or_read_only_membership_cannot_start_generation(
    db_url: str,
    opportunity: tuple[DecisionService, CountingProvider, UUID],
    change: dict[str, Any],
) -> None:
    service, provider, opportunity_id = opportunity
    before = counts(db_url, opportunity_id)
    with changed_row(db_url, "memberships", "user_id", MANAGER, change):
        assert service._can_request_recommendation_sync(opportunity_id, MANAGER) is False
        with pytest.raises(DecisionAuthorizationError):
            service.create_recommendation_sync(opportunity_id, MANAGER)
    assert counts(db_url, opportunity_id) == before
    assert provider.write_calls == 0


def test_seller_can_request_only_owned_opportunity(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, _, opportunity_id = opportunity
    with changed_row(db_url, "ares_opportunities", "id", opportunity_id, {"owner_user_id": SELLER}):
        assert service._can_request_recommendation_sync(opportunity_id, SELLER) is True
        created = service.create_recommendation_sync(opportunity_id, SELLER)
        assert created["status"] == "awaiting_approval"
        rec = service._get_recommendation_sync(created["recommendation_id"], SELLER)
        assert rec is not None and rec["can_decide"] is False


@pytest.mark.parametrize("actor", [SELLER, AUDITOR])
@pytest.mark.parametrize("verdict", ["approved", "rejected"])
def test_unauthorized_decision_does_not_create_intent_or_mutate_pending_approval(
    db_url: str,
    opportunity: tuple[DecisionService, CountingProvider, UUID],
    actor: str,
    verdict: str,
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    before = pending_state(db_url, created["recommendation_id"])
    with pytest.raises(DecisionAuthorizationError):
        service.decide_sync(
            created["recommendation_id"],
            DecideCommand.model_validate(
                {"verdict": verdict, "expected_version": created["version"]}
            ),
            actor,
        )
    assert pending_state(db_url, created["recommendation_id"]) == before
    assert provider.write_calls == 0
    detail = service._get_recommendation_sync(created["recommendation_id"], actor)
    assert detail is not None and detail["can_decide"] is False
    item = next(
        row
        for row in service._list_approvals_sync(actor)["items"]
        if row["recommendation_id"] == created["recommendation_id"]
    )
    assert item["can_decide"] is False


@pytest.mark.parametrize("change", [{"active": False}, {"role": "seller"}])
def test_membership_is_rechecked_at_decision_after_generation(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID], change: dict[str, Any]
) -> None:
    service, _, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, MANAGER)
    before = pending_state(db_url, created["recommendation_id"])
    with changed_row(db_url, "memberships", "user_id", MANAGER, change):
        with pytest.raises(DecisionAuthorizationError):
            service.decide_sync(
                created["recommendation_id"],
                DecideCommand(verdict="approved", expected_version=created["version"]),
                MANAGER,
            )
        assert pending_state(db_url, created["recommendation_id"]) == before
        detail = service._get_recommendation_sync(created["recommendation_id"], MANAGER)
        assert detail is not None and detail["can_decide"] is False


def test_expired_approval_cannot_decide_or_advertise_action(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    with changed_row(
        db_url,
        "approval_requests",
        "recommendation_id",
        created["recommendation_id"],
        {"expires_at": datetime.now(UTC) - timedelta(minutes=1)},
    ):
        before = pending_state(db_url, created["recommendation_id"])
        with pytest.raises(DecisionConflict, match="approval_expired"):
            service.decide_sync(
                created["recommendation_id"],
                DecideCommand(verdict="approved", expected_version=created["version"]),
                ADMIN,
            )
        assert pending_state(db_url, created["recommendation_id"]) == before
        detail = service._get_recommendation_sync(created["recommendation_id"], ADMIN)
        assert detail is not None and detail["can_decide"] is False
        assert provider.write_calls == 0


def test_http_admin_claim_does_not_override_persisted_seller_role(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, _, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    before = pending_state(db_url, created["recommendation_id"])
    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(
        user_id=UUID(SELLER), tenant_id=TENANT, email="synthetic@example.invalid", role="admin"
    )
    try:
        response = TestClient(app).post(
            f"/api/v1/recommendations/{created['recommendation_id']}/decide",
            json={"verdict": "approved", "expected_version": created["version"]},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "approval_role_required"
    finally:
        app.dependency_overrides.pop(require_user, None)
    assert pending_state(db_url, created["recommendation_id"]) == before


BLOCKS = [
    ("tenants", "id", {"status": "suspended"}, "tenant_inactive"),
    ("tenant_entitlements", "tenant_id", {"status": "suspended"}, "ares_connect_plan_inactive"),
    (
        "tenant_entitlements",
        "tenant_id",
        {"expires_at": datetime.now(UTC) - timedelta(days=1)},
        "ares_connect_plan_inactive",
    ),
    (
        "tenant_billing_state",
        "tenant_id",
        {
            "state": "degraded",
            "due_since": date.today() - timedelta(days=3),
            "grace_until": date.today() - timedelta(days=1),
        },
        "billing_degraded",
    ),
    (
        "tenant_billing_state",
        "tenant_id",
        {
            "state": "past_due",
            "due_since": date.today() - timedelta(days=3),
            "grace_until": date.today() - timedelta(days=1),
        },
        "billing_degraded",
    ),
    ("memberships", "user_id", {"active": False}, "decision_actor_forbidden"),
    ("memberships", "user_id", {"role": "seller"}, "approval_role_required"),
]


@pytest.mark.parametrize("table,key,change,error", BLOCKS)
def test_queued_write_revalidates_contract_and_approver_without_calling_crm(
    db_url: str,
    opportunity: tuple[DecisionService, CountingProvider, UUID],
    table: str,
    key: str,
    change: dict[str, Any],
    error: str,
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    approved = service.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        MANAGER,
    )
    target = MANAGER if table == "memberships" else TENANT
    with (
        changed_row(db_url, table, key, target, change),
        pytest.raises(ExecutionBlocked) as blocked,
    ):
        service.execute_intent_sync(approved["intent_id"])
    assert blocked.value.code == error
    assert provider.write_calls == 0
    action = service._get_action_sync(approved["intent_id"])
    assert action is not None
    assert action["intent"]["status"] == "cancelled"
    assert len(action["attempts"]) == 1
    assert action["attempts"][0]["error_code"] == error
    assert action["execution"] is None
    # Reactivating the contract cannot silently revive the already cancelled intent.
    replay = service.execute_intent_sync(approved["intent_id"])
    assert replay["status"] == "cancelled" and replay["duplicate"] is True
    assert provider.write_calls == 0
    with psycopg.connect(db_url) as db:
        state = db.execute(
            "select state from public.ares_opportunities where id=%s", (opportunity_id,)
        ).fetchone()
        outcomes = db.execute(
            "select count(*) from public.outcomes where intervention_id=%s",
            (created["intervention_id"],),
        ).fetchone()
    assert state == ("closed",)
    assert outcomes == (0,)


def test_provider_capability_revoked_after_approval_blocks_dispatch(
    opportunity: tuple[DecisionService, CountingProvider, UUID],
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    approved = service.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        ADMIN,
    )
    provider.task_enabled = False
    with pytest.raises(ExecutionBlocked, match="current_policy_denied"):
        service.execute_intent_sync(approved["intent_id"])
    assert provider.write_calls == 0


def test_escalated_current_policy_role_requires_new_authority_at_decision(
    db_url: str,
    opportunity: tuple[DecisionService, CountingProvider, UUID],
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    before = pending_state(db_url, created["recommendation_id"])
    service._policy = AdminOnlyTaskPolicy()
    with pytest.raises(DecisionAuthorizationError, match="approval_role_required"):
        service.decide_sync(
            created["recommendation_id"],
            DecideCommand(verdict="approved", expected_version=created["version"]),
            MANAGER,
        )
    detail = service._get_recommendation_sync(created["recommendation_id"], MANAGER)
    assert detail is not None and detail["can_decide"] is False
    assert pending_state(db_url, created["recommendation_id"]) == before
    assert provider.write_calls == 0


def test_escalated_current_policy_role_blocks_previously_approved_manager_intent(
    opportunity: tuple[DecisionService, CountingProvider, UUID],
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    approved = service.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        MANAGER,
    )
    service._policy = AdminOnlyTaskPolicy()
    with pytest.raises(ExecutionBlocked, match="approval_role_required"):
        service.execute_intent_sync(approved["intent_id"])
    assert provider.write_calls == 0


def test_past_due_with_current_grace_permits_one_idempotent_write(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    approved = service.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        ADMIN,
    )
    with changed_row(
        db_url,
        "tenant_billing_state",
        "tenant_id",
        TENANT,
        {
            "state": "past_due",
            "due_since": date.today() - timedelta(days=1),
            "grace_until": date.today() + timedelta(days=3),
        },
    ):
        assert service.execute_intent_sync(approved["intent_id"])["status"] == "succeeded"
        assert service.execute_intent_sync(approved["intent_id"])["duplicate"] is True
    assert provider.write_calls == 1


def test_worker_commercial_block_is_terminal_and_never_requeues_unsafe_write(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    approved = service.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        ADMIN,
    )
    with psycopg.connect(db_url, row_factory=dict_row) as db:
        job = db.execute(
            "update public.jobs set status='running',attempts=1 "
            "where kind='action.execute' and payload->>'intent_id'=%s returning *",
            (str(approved["intent_id"]),),
        ).fetchone()
    assert job is not None
    worker = TickWorker(db_url, "", "", provider=provider)
    with changed_row(db_url, "tenants", "id", TENANT, {"status": "suspended"}):
        with pytest.raises(ExecutionBlocked) as blocked:
            worker._process_job(dict(job))
        worker._fail_job(dict(job), blocked.value)
    with psycopg.connect(db_url) as db:
        result = db.execute(
            "select status,attempts,error_code,finished_at is not null "
            "from public.jobs where id=%s",
            (job["id"],),
        ).fetchone()
    assert result == ("failed", 1, "tenant_inactive", True)
    assert provider.write_calls == 0


def test_unreleased_contract_cannot_generate_decide_or_advertise_approval(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    before = pending_state(db_url, created["recommendation_id"])
    with changed_row(
        db_url,
        "tenant_billing_state",
        "tenant_id",
        TENANT,
        {
            "state": "degraded",
            "due_since": date.today() - timedelta(days=3),
            "grace_until": date.today() - timedelta(days=1),
        },
    ):
        assert not service._can_request_recommendation_sync(opportunity_id, ADMIN)
        with pytest.raises(DecisionAuthorizationError, match="billing_degraded"):
            service.create_recommendation_sync(opportunity_id, ADMIN)
        detail = service._get_recommendation_sync(created["recommendation_id"], ADMIN)
        assert detail and not detail["can_decide"]
        assert detail["execution_block_reason"] == "billing_degraded"
        with pytest.raises(DecisionAuthorizationError, match="billing_degraded"):
            service.decide_sync(
                created["recommendation_id"],
                DecideCommand(verdict="approved", expected_version=created["version"]),
                ADMIN,
            )
        assert pending_state(db_url, created["recommendation_id"]) == before
        assert provider.write_calls == 0


def test_restarted_worker_recovers_expired_lease_without_duplicate_crm_effect(
    db_url: str, opportunity: tuple[DecisionService, CountingProvider, UUID]
) -> None:
    service, provider, opportunity_id = opportunity
    created = service.create_recommendation_sync(opportunity_id, ADMIN)
    approved = service.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        ADMIN,
    )
    with psycopg.connect(db_url) as db:
        job_id = db.execute(
            "update public.jobs set status='running', attempts=1, lease_owner='crashed', "
            "lease_until=now()-interval '1 minute',run_after='1900-01-01' "
            "where kind='action.execute' and payload->>'intent_id'=%s returning id",
            (str(approved["intent_id"]),),
        ).fetchone()[0]
    # Simulate an accepted CRM request whose response was lost before local persistence.
    original_write = provider.create_task

    def lost_response(deal_id: str, title: str, key: str) -> CRMWriteResult:
        original_write(deal_id, title, key)
        raise RuntimeError("synthetic lost response")

    provider.create_task = lost_response
    first = TickWorker(db_url, "", "", provider=provider, worker_name="recovery-first")
    claimed = first._claim_jobs(1, ["action.execute"])
    assert claimed[0]["id"] == job_id
    with pytest.raises(RuntimeError) as error:
        first._process_job(claimed[0])
    first._fail_job(claimed[0], error.value)
    assert len(provider._writes) == 1
    provider.create_task = original_write
    with psycopg.connect(db_url) as db:
        db.execute("update public.jobs set run_after='1900-01-01' where id=%s", (job_id,))
    restarted = TickWorker(db_url, "", "", provider=provider, worker_name="recovery-restarted")
    retry = restarted._claim_jobs(1, ["action.execute"])
    assert retry[0]["id"] == job_id
    restarted._process_job(retry[0])
    assert len(provider._writes) == 1 and provider.write_calls == 2
    action = service._get_action_sync(approved["intent_id"])
    assert action and action["intent"]["status"] == "succeeded"
    assert action["execution"] and len(action["attempts"]) == 2
    with psycopg.connect(db_url) as db:
        assert db.execute(
            "select status,attempts from public.jobs where id=%s", (job_id,)
        ).fetchone() == ("succeeded", 3)


def test_plan_expiring_during_lock_wait_blocks_dispatch_using_wall_clock(db_url: str) -> None:
    provider = CountingProvider()
    transaction_started = Event()
    started_at: list[datetime] = []

    def dispatch_after_guard() -> None:
        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=3) as guard_db:
            guard_db.execute("set local lock_timeout='3s'")
            row = guard_db.execute("select now() as started_at").fetchone()
            assert row is not None
            started_at.append(row["started_at"])
            transaction_started.set()
            check_execution_contract(guard_db, TENANT)
            provider.create_task("deal-lock-regression", "Synthetic follow-up", str(uuid4()))

    # The guard starts a transaction before expiration, then waits behind a
    # contract update. Its original PostgreSQL now() must not authorize a write
    # after the wall clock has passed the new expiration.
    with (
        changed_row(
            db_url,
            "tenant_entitlements",
            "tenant_id",
            TENANT,
            {"expires_at": datetime.now(UTC) + timedelta(hours=1)},
        ),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        with psycopg.connect(db_url) as locker:
            locker.execute("select id from public.tenants where id=%s for update", (TENANT,))
            dispatch = pool.submit(dispatch_after_guard)
            assert transaction_started.wait(timeout=3)
            expiry = locker.execute(
                "update public.tenant_entitlements "
                "set expires_at=clock_timestamp()+interval '600 milliseconds' "
                "where tenant_id=%s and module='ares_connect' returning expires_at",
                (TENANT,),
            ).fetchone()
            assert expiry is not None and expiry[0] > started_at[0]
            locker.execute("select pg_sleep(0.7)")
            locker.commit()
        with pytest.raises(ExecutionBlocked, match="ares_connect_plan_inactive"):
            dispatch.result(timeout=3)
    assert provider.write_calls == 0
