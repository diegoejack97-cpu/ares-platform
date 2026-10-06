import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser
from ares.connectors.fake_crm import FakeCRMProvider
from ares.decision.model_factory import ModelResult
from ares.decision.models import (
    ActionAlternative,
    ActionDraft,
    DecideCommand,
    RecommendationOutput,
    TriageOutput,
)
from ares.decision.service import DecisionConflict, DecisionService
from ares.event_journal.models import IncomingCRMEvent
from ares.event_journal.service import PostgresEventJournal
from ares.intelligence.service import IntelligenceService
from ares.workers.tick import TickResult, TickWorker

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
ADMIN_ID = "10000000-0000-0000-0000-000000000001"
MANAGER_ID = "10000000-0000-0000-0000-000000000003"


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_m3_auditable_human_approved_idempotent_action_chain() -> None:
    assert DATABASE_URL is not None
    provider = FakeCRMProvider("test-secret")
    journal = PostgresEventJournal(DATABASE_URL, TENANT_ID)
    intelligence = IntelligenceService(DATABASE_URL, TENANT_ID)
    decision = DecisionService(DATABASE_URL, TENANT_ID, provider)
    now = datetime.now(UTC)
    aggregate_id = f"deal-m3-{uuid4().hex[:8]}"
    incoming = IncomingCRMEvent(
        provider_event_id=f"m3-{uuid4()}",
        event_type="deal.updated",
        aggregate_type="deal",
        aggregate_id=aggregate_id,
        occurred_at=now,
        data={
            "title": "Integração M3",
            "stage": "proposal",
            "previous_stage": "negotiation",
            "risk": "follow_up_overdue",
            "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
            "days_in_stage": 12,
            "next_step": None,
            "owner_id": None,
            "value": 125000,
            "currency": "BRL",
            "days_since_contact": 14,
        },
    )
    accepted = journal.record_sync(incoming)
    pipeline = intelligence.process_event_sync(accepted.event_id)
    assert pipeline.opportunity_id is not None

    with psycopg.connect(DATABASE_URL) as connection:
        prior_slots = connection.execute(
            "select agent_slots from public.tenant_quotas where tenant_id=%s", (TENANT_ID,)
        ).fetchone()[0]
        connection.execute(
            "update public.tenant_quotas set agent_slots=0 where tenant_id=%s", (TENANT_ID,)
        )
    try:
        with pytest.raises(DecisionConflict, match="agent_capacity_disabled"):
            decision.create_recommendation_sync(pipeline.opportunity_id, ADMIN_ID)
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.tenant_quotas set agent_slots=%s where tenant_id=%s",
                (prior_slots, TENANT_ID),
            )

    created = decision.create_recommendation_sync(pipeline.opportunity_id, ADMIN_ID)
    recommendation = decision._get_recommendation_sync(created["recommendation_id"])
    assert recommendation is not None
    assert recommendation["policy_verdict"] == "require_approval"
    assert recommendation["context_ref"] == pipeline.context_ref
    assert recommendation["generation_mode"] == "deterministic_fallback"

    approved = decision.decide_sync(
        created["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=created["version"]),
        MANAGER_ID,
    )
    assert approved["intent_id"] is not None
    with pytest.raises(DecisionConflict) as conflict:
        decision.decide_sync(
            created["recommendation_id"],
            DecideCommand(verdict="approved", expected_version=created["version"]),
            ADMIN_ID,
        )
    assert conflict.value.code == "stale_recommendation"

    executed = decision.execute_intent_sync(approved["intent_id"])
    replay = decision.execute_intent_sync(approved["intent_id"])
    assert executed["status"] == "succeeded"
    assert replay["duplicate"] is True

    with psycopg.connect(DATABASE_URL) as connection:
        chain = connection.execute(
            """
            select
              (select count(*) from public.action_intents where id = %s),
              (select count(*) from public.action_attempts where intent_id = %s),
              (select count(*) from public.action_executions where intent_id = %s),
              (select count(*) from public.outcomes where intervention_id = %s),
              (select state_after_ref is not null from public.ares_interventions where id = %s),
              (select attribution_level::text from public.outcomes where intervention_id = %s),
              (select incremental_value is null from public.outcomes where intervention_id = %s)
            """,
            (
                approved["intent_id"],
                approved["intent_id"],
                approved["intent_id"],
                created["intervention_id"],
                created["intervention_id"],
                created["intervention_id"],
                created["intervention_id"],
            ),
        ).fetchone()
    assert chain == (1, 1, 1, 1, True, "observed", True)


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_m3_policy_allow_authorizes_low_risk_action_without_dead_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    provider = FakeCRMProvider("test-secret")
    journal = PostgresEventJournal(DATABASE_URL, TENANT_ID)
    intelligence = IntelligenceService(DATABASE_URL, TENANT_ID)
    decision = DecisionService(DATABASE_URL, TENANT_ID, provider)
    now = datetime.now(UTC)
    accepted = journal.record_sync(
        IncomingCRMEvent(
            provider_event_id=f"m3-allow-{uuid4()}",
            event_type="deal.updated",
            aggregate_type="deal",
            aggregate_id=f"deal-m3-allow-{uuid4().hex[:8]}",
            occurred_at=now,
            data={
                "title": "Ação de baixo risco",
                "stage": "proposal",
                "risk": "follow_up_overdue",
                "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
                "days_in_stage": 10,
                "next_step": None,
                "value": 42000,
                "currency": "BRL",
            },
        )
    )
    pipeline = intelligence.process_event_sync(accepted.event_id)
    assert pipeline.opportunity_id is not None
    generated = ModelResult(
        output=RecommendationOutput(
            recommended_action=ActionDraft(
                action_kind="add_note",
                payload={"body": "ARES sinalizou risco; revisar o próximo passo."},
            ),
            rationale="Registrar contexto de baixo risco para o vendedor responsável.",
            confidence=0.81,
            alternatives=[
                ActionAlternative(
                    label="Criar tarefa",
                    action=ActionDraft(
                        action_kind="create_task", payload={"title": "Revisar oportunidade"}
                    ),
                    tradeoff="Exige aprovação humana antes da escrita.",
                )
            ],
            triage=TriageOutput(urgency="high", reason="Follow-up vencido.", evidence_refs=[]),
        ),
        generation_mode="deterministic_fallback",
        model_id=None,
        prompt_hash="allow-test",
        status="degraded",
    )
    monkeypatch.setattr(decision._models, "generate", lambda *_args: generated)

    created = decision.create_recommendation_sync(pipeline.opportunity_id, ADMIN_ID)
    assert created["status"] == "authorized"
    assert created["intent_id"] is not None
    executed = decision.execute_intent_sync(created["intent_id"])
    assert executed["status"] == "succeeded"

    with psycopg.connect(DATABASE_URL) as connection:
        chain = connection.execute(
            """
            select
              (select count(*) from public.approval_requests where recommendation_id = %s),
              (select actor_type::text from public.decisions where recommendation_id = %s),
              (select actor_type::text from public.action_intents where id = %s),
              (select executed_action->>'action_kind'
                from public.action_executions where intent_id = %s)
            """,
            (
                created["recommendation_id"],
                created["recommendation_id"],
                created["intent_id"],
                created["intent_id"],
            ),
        ).fetchone()
    assert chain == (0, "ares_agent", "ares_agent", "add_note")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_m3_http_contract_returns_409_and_executes_via_background_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    # This test exercises the optional development background runner explicitly;
    # the operator's local .env may correctly disable it in favor of the daemon.
    monkeypatch.setattr("ares.api.app.settings.background_execution", True)
    now = datetime.now(UTC)
    journal = PostgresEventJournal(DATABASE_URL, TENANT_ID)
    intelligence = IntelligenceService(DATABASE_URL, TENANT_ID)
    accepted = journal.record_sync(
        IncomingCRMEvent(
            provider_event_id=f"m3-api-{uuid4()}",
            event_type="deal.updated",
            aggregate_type="deal",
            aggregate_id=f"deal-m3-api-{uuid4().hex[:8]}",
            occurred_at=now,
            data={
                "title": "Contrato HTTP M3",
                "stage": "proposal",
                "risk": "follow_up_overdue",
                "next_follow_up_at": (now - timedelta(days=2)).isoformat(),
                "days_in_stage": 9,
                "next_step": None,
                "value": 88000,
                "currency": "BRL",
            },
        )
    )
    pipeline = intelligence.process_event_sync(accepted.event_id)
    assert pipeline.opportunity_id is not None

    monkeypatch.setitem(
        app.dependency_overrides,
        require_user,
        lambda: AuthenticatedUser(
            user_id=UUID(ADMIN_ID), tenant_id=TENANT_ID, email="admin@ares.local", role="admin"
        ),
    )
    client = TestClient(app)
    created = client.post(
        f"/api/v1/opportunities/{pipeline.opportunity_id}/recommendations",
        json={"trigger": "manual"},
    )
    assert created.status_code == 202
    rec = client.get(f"/api/v1/recommendations/{created.json()['recommendation_id']}").json()
    stale = client.post(
        f"/api/v1/recommendations/{rec['id']}/decide",
        json={"verdict": "approved", "expected_version": rec["version"] + 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_recommendation"

    # The HTTP background task uses the real durable claim/execute implementation.
    # Bound its batch by this isolated database's pending actions, so unrelated
    # projection jobs from earlier tests cannot starve this newly approved intent.
    with psycopg.connect(DATABASE_URL) as connection:
        queue_count = connection.execute(
            "select count(*) from public.jobs where kind='action.execute' and status='queued'"
        ).fetchone()
    assert queue_count is not None
    actual_tick = TickWorker.run_once

    def drain_actions(worker: TickWorker) -> TickResult:
        return actual_tick(
            worker,
            batch_size=queue_count[0] + 1,
            job_kinds=["action.execute"],
            scan_sentinels=False,
        )

    monkeypatch.setattr(TickWorker, "run_once", drain_actions)

    approved = client.post(
        f"/api/v1/recommendations/{rec['id']}/decide",
        json={"verdict": "approved", "expected_version": rec["version"]},
    )
    assert approved.status_code == 200
    action = client.get(f"/api/v1/actions/{approved.json()['intent_id']}")
    assert action.status_code == 200
    assert action.json()["intent"]["status"] == "succeeded"
    assert action.json()["execution"]["executed_action"]["action_kind"] == "create_task"
    assert action.json()["execution"]["target"]["resolved_from"] == rec["context_ref"]
