"""Synthetic full-portfolio selection and single DecisionService action path."""

# ruff: noqa: E501
import json
from uuid import uuid4

import pytest
import test_postgres_agent_runtime as base
from psycopg.types.json import Jsonb

from ares.agents.commercial_contracts import CommercialConfig, PortfolioRequest
from ares.agents.commercial_service import CommercialService
from ares.auth.models import AuthenticatedUser
from ares.connectors.fake_crm import FakeCRMProvider
from ares.decision.models import DecideCommand
from ares.decision.service import DecisionConflict, DecisionService
from ares.intelligence.context_builder import ContextBuilder

fixture = base.fixture
query = base.query
pytestmark = base.pytestmark


@pytest.fixture
def case(fixture):
    _, user, opp, snapshot, _, seller = fixture
    query(
        fixture,
        "update public.tenant_quotas set agent_slots=3,ai_daily_budget_brl=1000,ai_monthly_budget_brl=10000 where tenant_id=%s",
        (user.tenant_id,),
    )
    deal = uuid4()
    query(
        fixture,
        "insert into public.deals(id,tenant_id,title,external_id,status,value,currency,canonical_stage) values(%s,%s,'Synthetic older high value','deal-001','open',999999,'BRL','proposal')",
        (deal, user.tenant_id),
    )
    query(
        fixture,
        "update public.ares_opportunities set deal_id=%s,score=0.99,priority=0,sla_at='2000-01-01' where id=%s",
        (deal, opp),
    )
    query(
        fixture,
        "update public.context_snapshots set facts_json=%s where id=%s",
        (
            Jsonb(
                {
                    "deal": {
                        "title": "Synthetic older high value",
                        "external_id": "deal-001",
                        "value": 999999,
                        "currency": "BRL",
                    }
                }
            ),
            snapshot,
        ),
    )
    service = CommercialService(base.URL)
    service.configure(
        user,
        CommercialConfig(
            expected_version=0,
            enabled=True,
            recommendations_enabled=True,
            reason="Synthetic phase 6 and 7",
        ),
    )
    yield fixture, service
    # Preserve the base fixture's teardown order by clearing all new links first.
    for table in (
        "messages",
        "conversations",
        "recommendation_context_guards",
        "commercial_proposals",
        "portfolio_analyses",
        "commercial_routines",
        "outcomes",
        "action_executions",
        "action_attempts",
        "jobs",
        "action_intents",
        "decisions",
        "approval_requests",
        "policy_decisions",
        "recommendations",
    ):
        query(fixture, f"delete from public.{table} where tenant_id=%s", (user.tenant_id,))
    query(
        fixture,
        "update public.agent_runs set parent_run_id=null where tenant_id=%s",
        (user.tenant_id,),
    )
    for table in ("model_usage", "ai_usage_ledger", "ai_budget_reservations", "agent_runs"):
        query(fixture, f"delete from public.{table} where tenant_id=%s", (user.tenant_id,))
    query(fixture, "delete from public.ares_interventions where tenant_id=%s", (user.tenant_id,))
    query(
        fixture,
        "delete from public.opportunity_state_transitions where tenant_id=%s",
        (user.tenant_id,),
    )
    query(
        fixture,
        "update public.ares_opportunities set deal_id=null where tenant_id=%s",
        (user.tenant_id,),
    )
    query(fixture, "delete from public.deals where tenant_id=%s", (user.tenant_id,))


def process(case, id, stage):
    fixture, service = case
    service.process(fixture[1].tenant_id, {"analysis_id": str(id), "stage": stage})


def test_full_universe_selection_and_personal_two_agent_briefing(case):
    fixture, service = case
    user = fixture[1]
    # A high-value older deal must beat many newer records before projection cuts.
    for i in range(30):
        query(
            fixture,
            "insert into public.deals(tenant_id,title,status,value,currency,canonical_stage) values(%s,%s,'open',1,'BRL','proposal')",
            (user.tenant_id, f"Synthetic newer {i}"),
        )
    request = PortfolioRequest(criterion="value", currency="BRL")
    source = ContextBuilder(base.URL).portfolio(user, "value", "BRL")
    assert source["result"]["metrics"]["total"] == 31
    assert json.loads(source["content"])["matches"][0]["id"] == str(fixture[2])
    opened = service.start(user, request)
    assert service.start(user, request)["reused"]
    process(case, opened["id"], 0)
    process(case, opened["id"], 1)
    view = service.latest(user, request)
    assert view["state"] == "degraded" and len(view["run_ids"]) == 2
    assert view["ranking"]["ranking"][0]["opportunity_id"] == str(fixture[2])
    process(case, opened["id"], 1)
    assert len(service.latest(user, request)["run_ids"]) == 2


def test_scope_change_invalidates_analysis_and_seller_cannot_see_foreign_candidates(case):
    fixture, service = case
    user = fixture[1]
    seller = AuthenticatedUser(tenant_id=user.tenant_id, user_id=fixture[5], role="seller")
    assert ContextBuilder(base.URL).portfolio(seller, "urgency", None)["candidate_refs"] == []
    opened = service.start(user, PortfolioRequest())
    query(
        fixture,
        "update public.memberships set active=false where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    process(case, opened["id"], 0)
    assert (
        query(fixture, "select status from public.portfolio_analyses where id=%s", (opened["id"],))[
            0
        ]["status"]
        == "failed"
    )
    assert (
        query(
            fixture,
            "select count(*) n from public.model_usage where tenant_id=%s",
            (user.tenant_id,),
        )[0]["n"]
        == 0
    )


def test_separate_proposal_writing_human_approval_and_single_execution(case):
    fixture, _ = case
    user, opp = fixture[1], fixture[2]
    service = DecisionService(base.URL, user.tenant_id, FakeCRMProvider("synthetic"))
    made = service.create_recommendation_sync(opp, str(user.user_id))
    assert (
        service.create_recommendation_sync(opp, str(user.user_id))["recommendation_id"]
        == made["recommendation_id"]
    )
    rows = query(
        fixture,
        "select agent_name from public.agent_runs where tenant_id=%s and intervention_id=%s order by started_at",
        (user.tenant_id, made["intervention_id"]),
    )
    assert [r["agent_name"] for r in rows] == ["action-recommender", "followup-writer"]
    assert (
        query(
            fixture,
            "select count(*) n from public.action_intents where tenant_id=%s",
            (user.tenant_id,),
        )[0]["n"]
        == 0
    )
    approved = service.decide_sync(
        made["recommendation_id"],
        DecideCommand(verdict="approved", expected_version=made["version"]),
        str(user.user_id),
    )
    first = service.execute_intent_sync(approved["intent_id"])
    assert first["status"] == "succeeded"
    assert service.execute_intent_sync(approved["intent_id"])["duplicate"]
    assert (
        query(
            fixture,
            "select count(*) n from public.action_executions where tenant_id=%s",
            (user.tenant_id,),
        )[0]["n"]
        == 1
    )


def test_changed_deal_blocks_old_proposal_before_decision(case):
    fixture, _ = case
    user = fixture[1]
    service = DecisionService(base.URL, user.tenant_id, FakeCRMProvider("synthetic"))
    made = service.create_recommendation_sync(fixture[2], str(user.user_id))
    query(
        fixture,
        "update public.deals set value=0,version=version+1 where tenant_id=%s",
        (user.tenant_id,),
    )
    with pytest.raises(DecisionConflict, match="recommendation_context_stale"):
        service.decide_sync(
            made["recommendation_id"],
            DecideCommand(verdict="approved", expected_version=made["version"]),
            str(user.user_id),
        )
    assert (
        query(
            fixture,
            "select count(*) n from public.action_intents where tenant_id=%s",
            (user.tenant_id,),
        )[0]["n"]
        == 0
    )


def test_proactive_cooldown_and_company_daily_cap(case):
    fixture, service = case
    user = fixture[1]
    config = service.configuration(user)
    service.configure(
        user,
        CommercialConfig(
            expected_version=config["version"],
            enabled=True,
            recommendations_enabled=True,
            proactive_enabled=True,
            daily_proposal_limit=1,
            reason="Synthetic opt in",
        ),
    )
    assert service.propose(user, [str(fixture[2])], "finding") == 1
    assert service.propose(user, [str(fixture[2])], "finding") == 0
    assert (
        query(
            fixture,
            "select count(*) n from public.jobs where tenant_id=%s and kind='commercial.propose'",
            (user.tenant_id,),
        )[0]["n"]
        == 1
    )


def test_concurrent_stage_has_one_dispatch_and_recovery_never_calls_again(case):
    from concurrent.futures import ThreadPoolExecutor

    fixture, service = case
    opened = service.start(fixture[1], PortfolioRequest())
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda _: process(case, opened["id"], 0), range(2)))
    assert (
        len(
            query(
                fixture,
                "select id from public.agent_runs where tenant_id=%s and agent_name='portfolio-prioritizer'",
                (fixture[1].tenant_id,),
            )
        )
        == 1
    )
    service.process(
        fixture[1].tenant_id, {"analysis_id": str(opened["id"]), "stage": 0, "recovered": True}
    )
    assert (
        len(
            query(
                fixture,
                "select id from public.agent_runs where tenant_id=%s and agent_name='portfolio-prioritizer'",
                (fixture[1].tenant_id,),
            )
        )
        == 1
    )


def test_unknown_candidate_is_rejected_before_briefing(case):
    from ares.agents.commercial_contracts import PortfolioRanking, RankedCandidate
    from ares.agents.executor import AgentOutcome
    from ares.ai.usage import UsageObservation

    class InvalidExecutor:
        async def execute(self, definition, payload, model_id):
            return AgentOutcome(
                PortfolioRanking(
                    summary="Synthetic invalid ranking",
                    ranking=[
                        RankedCandidate(
                            opportunity_id=uuid4(),
                            reason="Foreign candidate",
                            evidence_refs=payload.evidence_refs[:1],
                        )
                    ],
                    facts=[],
                    limitations=[],
                ),
                UsageObservation(status="not_called"),
            )

    fixture, service = case
    service.executor = InvalidExecutor()
    opened = service.start(fixture[1], PortfolioRequest())
    process(case, opened["id"], 0)
    assert service.latest(fixture[1], PortfolioRequest())["state"] == "failed"
    assert not query(
        fixture,
        "select id from public.agent_runs where tenant_id=%s and agent_name='commercial-analyst'",
        (fixture[1].tenant_id,),
    )


def test_stale_pending_can_be_replaced_and_validity_matches_approval(case):
    fixture, _ = case
    user = fixture[1]
    service = DecisionService(base.URL, user.tenant_id, FakeCRMProvider("synthetic"))
    old = service.create_recommendation_sync(fixture[2], str(user.user_id))
    query(
        fixture,
        "update public.deals set version=version+1,value=123 where tenant_id=%s",
        (user.tenant_id,),
    )
    approvals = service._list_approvals_sync(str(user.user_id))
    assert not approvals["items"][0]["can_decide"]
    assert approvals["items"][0]["execution_block_reason"] == "recommendation_context_stale"
    new = service.create_recommendation_sync(fixture[2], str(user.user_id))
    assert new["recommendation_id"] != old["recommendation_id"]
    assert (
        query(
            fixture,
            "select status from public.recommendations where id=%s",
            (old["recommendation_id"],),
        )[0]["status"]
        == "superseded"
    )
    row = query(
        fixture,
        "select r.expires_at as rec,a.expires_at as approval,p.expires_at as policy,g.valid_until as guard from public.recommendations r join public.approval_requests a on a.recommendation_id=r.id join public.policy_decisions p on p.recommendation_id=r.id join public.recommendation_context_guards g on g.recommendation_id=r.id where r.id=%s",
        (new["recommendation_id"],),
    )[0]
    assert row["rec"] == row["approval"] == row["policy"] == row["guard"]


def test_dashboard_and_chat_reuse_same_current_analysis(case):
    from pydantic import SecretStr

    from ares.agents.commercial_contracts import PortfolioView
    from ares.chat.service import ChatService
    from ares.config import Settings

    fixture, service = case
    user = fixture[1]
    opened = service.start(user, PortfolioRequest())
    process(case, opened["id"], 0)
    process(case, opened["id"], 1)
    dashboard = PortfolioView.model_validate(service.latest(user, PortfolioRequest()))
    chat = ChatService(
        Settings(_env_file=None, database_url=base.URL, openai_api_key=SecretStr(""))
    )
    prepared = chat.prepare(user, None, "Quais oportunidades urgentes devemos priorizar?")
    assert prepared["portfolio_analysis"]["analysis_id"] == dashboard.analysis_id
    assert prepared["portfolio_analysis"]["run_ids"] == dashboard.run_ids
    assert prepared["deterministic"]
    response = "".join(chat.stream(prepared))
    assert "Synthetic older high value" in response
    query(
        fixture,
        "update public.deals set value=value+1,version=version+1 where tenant_id=%s",
        (user.tenant_id,),
    )
    assert service.latest(user, PortfolioRequest())["state"] == "stale"
