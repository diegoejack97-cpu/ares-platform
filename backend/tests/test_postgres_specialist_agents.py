"""Specialized chain, relevant freshness, rollout and decision-safe fallback."""
# ruff: noqa: E501

from uuid import uuid4

import pytest
import test_postgres_agent_runtime as base

from ares.agents.catalog import SPECIALIST_SEQUENCE
from ares.agents.contracts import RoutineCommand, StartAnalysis
from ares.agents.executor import AgentOutcome, AgnoExecutor
from ares.agents.runtime import AgentRuntimeError
from ares.agents.specialists import DiagnosisAnalysis, FactClaim, SpecialistInput, TriageAnalysis
from ares.ai.usage import UsageObservation
from ares.auth.models import AuthenticatedUser

fixture = base.fixture
query = base.query
pytestmark = base.pytestmark


class Executor:
    invalid = False
    human = False
    fail_diagnosis = False

    async def execute(self, definition, payload, model_id):
        assert isinstance(payload, SpecialistInput)
        facts = [FactClaim(path="/deal/value", value="999" if self.invalid else "0")]
        common = dict(
            summary="Evidência comercial disponível para revisão humana.",
            facts=facts,
            evidence_refs=payload.evidence_refs,
            limitations=[],
            needs_human_review=True,
        )
        if definition.agent_id == SPECIALIST_SEQUENCE[0]:
            output = TriageAnalysis(
                **common,
                category="commercial_risk",
                proposed_urgency="high",
                route="human_review" if self.human else "diagnosis",
            )
        else:
            if self.fail_diagnosis:
                raise RuntimeError("synthetic failure")
            assert isinstance(payload.previous, TriageAnalysis)
            output = DiagnosisAnalysis(**common, hypotheses=[])
        return AgentOutcome(output, UsageObservation(status="not_called"))


@pytest.fixture
def specialized(fixture):
    runtime, user, *_ = fixture
    runtime.configure_specialists(
        user, RoutineCommand(enabled=True, expected_version=1, reason="Synthetic specialization")
    )
    runtime.executor = Executor()
    return fixture


def test_separate_runs_current_analysis_and_semantic_reuse(specialized):
    runtime, user, opportunity, snapshot, *_ = specialized
    chain = base.start(specialized)
    assert runtime.process_next().succeeded and runtime.process_next().succeeded
    result = runtime.get(user, chain["id"])
    assert [item["agent_name"] for item in result["runs"]] == list(SPECIALIST_SEQUENCE)
    report = runtime.analysis(user, opportunity)
    assert report["state"] == "ready" and report["triage"]["proposed_urgency"] == "high"
    assert result["handoffs"][0]["schema_version"] == "triage-output.v1"
    newer = uuid4()
    query(
        specialized,
        "insert into public.context_snapshots(id,tenant_id,opportunity_id,snapshot_version,opportunity_state,content_hash,source,facts_json,citations_json) select %s,tenant_id,opportunity_id,2,opportunity_state,'different-backlog','ares',facts_json,citations_json from public.context_snapshots where id=%s",
        (newer, snapshot),
    )
    assert runtime.analysis(user, opportunity)["state"] == "ready"
    reused_command = StartAnalysis(
        opportunity_id=opportunity, context_ref=newer, idempotency_key=uuid4()
    )
    reused = runtime.start(user, reused_command)
    assert reused["id"] == chain["id"]
    query(specialized, "update public.ares_opportunities set score=0.8 where id=%s", (opportunity,))
    assert runtime.analysis(user, opportunity)["state"] == "stale"
    assert runtime.start(user, reused_command)["id"] == chain["id"]
    with pytest.raises(AgentRuntimeError, match="agent_idempotency_conflict"):
        runtime.start(user, reused_command.model_copy(update={"context_ref": snapshot}))
    assert (
        runtime.start(
            user,
            StartAnalysis(opportunity_id=opportunity, context_ref=newer, idempotency_key=uuid4()),
        )["id"]
        != chain["id"]
    )


def test_reduced_capacity_hides_analysis_and_blocks_execution(specialized):
    runtime, user, opportunity, *_ = specialized
    base.start(specialized)
    assert runtime.process_next().succeeded and runtime.process_next().succeeded
    query(
        specialized,
        "update public.tenant_quotas set agent_slots=1 where tenant_id=%s",
        (user.tenant_id,),
    )
    result = runtime.analysis(user, opportunity)
    assert result["state"] == "capacity_missing" and not result["can_request"]
    assert result["triage"] is None and result["diagnosis"] is None
    with pytest.raises(AgentRuntimeError, match="agent_routine_unavailable"):
        base.start(specialized)


@pytest.mark.parametrize(
    "change,code",
    [
        ("facts", "agent_fact_invalid"),
        ("access", "agent_access_denied"),
        ("flag", "agent_specialists_disabled"),
        ("data", "agent_analysis_stale"),
    ],
)
def test_invalid_or_revoked_analysis_never_handoffs(specialized, change, code):
    runtime, user, opportunity, *_ = specialized
    chain = base.start(specialized)
    if change == "facts":
        runtime.executor.invalid = True
    elif change == "access":
        query(
            specialized,
            "update public.memberships set active=false where tenant_id=%s and user_id=%s",
            (user.tenant_id, user.user_id),
        )
    elif change == "flag":
        runtime.configure_specialists(
            user, RoutineCommand(enabled=False, expected_version=2, reason="Synthetic rollback")
        )
    else:
        query(
            specialized,
            "update public.ares_opportunities set score=0.7 where id=%s",
            (opportunity,),
        )
    assert not runtime.process_next().succeeded
    row = query(
        specialized,
        "select status,error_code from public.agent_workflows where id=%s",
        (chain["id"],),
    )[0]
    assert row["status"] == "blocked" and row["error_code"] == code
    assert not query(
        specialized, "select 1 from public.agent_handoffs where workflow_id=%s", (chain["id"],)
    )


def test_missing_model_and_diagnosis_failure_preserve_readable_opportunity(specialized):
    runtime, user, opportunity, *_ = specialized
    runtime.executor = AgnoExecutor("")
    base.start(specialized)
    assert runtime.process_next().succeeded
    assert runtime.analysis(user, opportunity)["state"] == "degraded"
    runtime.executor = Executor()
    runtime.executor.fail_diagnosis = True
    base.start(specialized)
    assert runtime.process_next().succeeded
    assert not runtime.process_next().succeeded
    assert runtime.analysis(user, opportunity)["state"] == "failed"
    assert (
        query(
            specialized, "select state from public.ares_opportunities where id=%s", (opportunity,)
        )[0]["state"]
        == "prioritized"
    )


def test_human_route_and_flag_management_are_server_authorized(specialized):
    runtime, user, opportunity, snapshot, _, seller = specialized
    runtime.executor.human = True
    base.start(specialized)
    assert runtime.process_next().succeeded and runtime.process_next() is None
    assert runtime.analysis(user, opportunity)["state"] == "human_review"
    foreign = AuthenticatedUser(user_id=seller, tenant_id=user.tenant_id, role="admin")
    with pytest.raises(AgentRuntimeError, match="agent_admin_required"):
        runtime.configure_specialists(
            foreign, RoutineCommand(enabled=False, expected_version=2, reason="Synthetic denied")
        )
    with pytest.raises(AgentRuntimeError, match="agent_scope_denied"):
        runtime.analysis(foreign, opportunity)
    query(
        specialized,
        "update public.agent_workflows set analysis_valid_until=now()-interval '1 second' where tenant_id=%s",
        (user.tenant_id,),
    )
    assert runtime.analysis(user, opportunity)["state"] == "stale"


@pytest.mark.parametrize("mutate_during_generation", [False, True])
def test_recommendation_consumes_independent_triage_only_while_current(
    specialized, mutate_during_generation
):
    from ares.connectors.fake_crm import FakeCRMProvider
    from ares.decision.service import DecisionConflict, DecisionService

    runtime, user, opportunity, *_ = specialized
    base.start(specialized)
    assert runtime.process_next().succeeded and runtime.process_next().succeeded
    service = DecisionService(base.URL, user.tenant_id, FakeCRMProvider("synthetic"))
    original = service._models.generate

    def generate(tenant, context):
        assert context["validated_triage"]["urgency"] == "high"
        result = original(tenant, context)
        if mutate_during_generation:
            query(
                specialized,
                "update public.ares_opportunities set score=0.9 where id=%s",
                (opportunity,),
            )
        return result

    service._models.generate = generate
    try:
        if mutate_during_generation:
            with pytest.raises(DecisionConflict, match="recommendation_analysis_stale"):
                service.create_recommendation_sync(opportunity, str(user.user_id))
            assert not query(
                specialized,
                "select 1 from public.recommendations where tenant_id=%s",
                (user.tenant_id,),
            )
            assert query(
                specialized,
                "select status,error_code from public.agent_runs where tenant_id=%s and agent_name='follow-up+triage'",
                (user.tenant_id,),
            ) == [{"status": "failed", "error_code": "recommendation_analysis_stale"}]
        else:
            result = service.create_recommendation_sync(opportunity, str(user.user_id))
            run = query(
                specialized,
                "select agent_name,output_json,output_schema_version from public.agent_runs where id=%s",
                (result["run_id"],),
            )[0]
            assert (
                run["agent_name"] == "follow-up"
                and run["output_schema_version"] == "recommendation.v2"
            )
            assert run["output_json"]["analysis_source"]["mode"] == "independent_triage"
            assert query(
                specialized,
                "select urgency,output_schema_version from public.recommendations where id=%s",
                (result["recommendation_id"],),
            )[0] == {"urgency": "high", "output_schema_version": "recommendation.v2"}
    finally:
        query(
            specialized,
            "update public.agent_runs set intervention_id=null where tenant_id=%s",
            (user.tenant_id,),
        )
        for table in [
            "approval_requests",
            "policy_decisions",
            "recommendations",
            "opportunity_state_transitions",
            "ares_interventions",
        ]:
            query(specialized, f"delete from public.{table} where tenant_id=%s", (user.tenant_id,))
