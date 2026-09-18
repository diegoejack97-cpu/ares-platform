# ruff: noqa: E501
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.command_center.models import CommandCenterSummary
from ares.command_center.service import (
    MAIN_PATH_STATES,
    CommandCenterDenied,
    CommandCenterService,
)
from ares.impact.service import ImpactService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


class Fixture:
    """One rolled-back connection shared by the service and the assertions."""

    def __init__(self, db: psycopg.Connection[Any]):
        self.db = db
        now = datetime.now(UTC)
        self.now = now
        self.tenant = uuid4()
        self.manager, self.seller = uuid4(), uuid4()
        self.opportunities: dict[str, UUID] = {}
        self.correlation = uuid4()
        run = db.execute
        for user in (self.manager, self.seller):
            run("insert into auth.users(id) values(%s)", (user,))
        run(
            "insert into public.tenants(id,name,slug) values(%s,'Synthetic command center',%s)",
            (self.tenant, str(self.tenant)),
        )
        run(
            "insert into public.tenant_quotas(tenant_id,seats_limit,ai_daily_budget_brl,ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) values(%s,10,0,0,5,'synthetic test',%s)",
            (self.tenant, self.manager),
        )
        run(
            "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'manager'),(%s,%s,'seller')",
            (self.tenant, self.manager, self.tenant, self.seller),
        )
        run(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) values(%s,'ares_connect','active',%s)",
            (self.tenant, self.manager),
        )
        run(
            "insert into public.connections(tenant_id,provider,status,auth_type,capabilities) values(%s,'fake-crm','healthy','shared_secret','{}'),(%s,'client-crm','degraded','oauth','{}')",
            (self.tenant, self.tenant),
        )
        deals = {
            "A": ("Negócio A", Decimal("1000")),
            "B": ("Negócio B", Decimal("2000")),
            "C": ("Negócio C", Decimal("4000")),
            "D": ("Negócio D", None),
        }
        specs = {
            "A": (0, now - timedelta(days=1), None),
            "B": (0, now + timedelta(hours=3), self.seller),
            "C": (2, now + timedelta(hours=30), None),
            "D": (3, None, None),
        }
        for key, (title, value) in deals.items():
            deal = uuid4()
            run(
                "insert into public.deals(id,tenant_id,title,value,currency,external_id) values(%s,%s,%s,%s,'BRL',%s)",
                (deal, self.tenant, title, value, f"deal-{key}"),
            )
            priority, sla, owner = specs[key]
            opportunity = uuid4()
            self.opportunities[key] = opportunity
            run(
                "insert into public.ares_opportunities(id,tenant_id,deal_id,opportunity_type,state,score,priority,owner_user_id,sla_at,opened_at,correlation_id,primary_signal_type,signal_count) values(%s,%s,%s,'revenue_recovery','prioritized',0.7,%s,%s,%s,%s,%s,'follow_up_overdue',2)",
                (
                    opportunity,
                    self.tenant,
                    deal,
                    priority,
                    owner,
                    sla,
                    now - timedelta(days=2),
                    self.correlation,
                ),
            )
            self.transition(opportunity, "detected", now - timedelta(days=2))
        for key in ("A", "B"):
            self.transition(
                self.opportunities[key], "prioritized", now - timedelta(days=2, hours=-1)
            )
        a = self.opportunities["A"]
        self.transition(a, "awaiting_decision", now - timedelta(days=1, hours=2))
        self.transition(a, "authorized", now - timedelta(days=1, hours=1))
        self.intervention = uuid4()
        context = uuid4()
        run(
            "insert into public.context_snapshots(id,tenant_id,opportunity_id,snapshot_version,opportunity_state,content_hash,source,source_ref,facts_json) values(%s,%s,%s,1,'prioritized','synthetic-cc','ares','synthetic','{}')",
            (context, self.tenant, a),
        )
        run(
            "insert into public.ares_interventions(id,tenant_id,opportunity_id,correlation_id,state_before_ref,status,source,created_at) values(%s,%s,%s,%s,%s,'observing','ares',%s)",
            (
                self.intervention,
                self.tenant,
                a,
                self.correlation,
                context,
                now - timedelta(days=1, hours=3),
            ),
        )
        recommendation, policy = uuid4(), uuid4()
        run(
            "insert into public.recommendations(id,tenant_id,intervention_id,opportunity_id,correlation_id,kind,recommended_action,rationale,confidence,urgency) values(%s,%s,%s,%s,%s,'next_best_action','{\"action_kind\":\"create_task\"}','synthetic',0.9,'critical')",
            (recommendation, self.tenant, self.intervention, a, self.correlation),
        )
        run(
            "insert into public.policy_decisions(id,tenant_id,policy_set,policy_version,inputs_hash,verdict) values(%s,%s,'ares-connect-actions',1,'hash','require_approval')",
            (policy, self.tenant),
        )
        run(
            "insert into public.approval_requests(id,tenant_id,intervention_id,recommendation_id,policy_decision_id,opportunity_id,correlation_id,expires_at,required_role) values(%s,%s,%s,%s,%s,%s,%s,%s,'manager')",
            (
                uuid4(),
                self.tenant,
                self.intervention,
                recommendation,
                policy,
                a,
                self.correlation,
                now + timedelta(hours=2),
            ),
        )
        run(
            "insert into public.decisions(tenant_id,intervention_id,recommendation_id,policy_decision_id,correlation_id,actor_type,actor_id,verdict,reason,source,decided_at) values(%s,%s,%s,%s,%s,'human',%s,'approved','ok','human',%s)",
            (
                self.tenant,
                self.intervention,
                recommendation,
                policy,
                self.correlation,
                str(self.manager),
                now - timedelta(hours=20),
            ),
        )
        run(
            "insert into public.action_executions(tenant_id,intervention_id,correlation_id,executed_action,target,actor_type,source,status,idempotency_key,attempts,finished_at) values(%s,%s,%s,%s,'{}','system','ares','failed',%s,2,%s)",
            (
                self.tenant,
                self.intervention,
                self.correlation,
                Jsonb({"action_kind": "create_task"}),
                f"cc-{uuid4()}",
                now - timedelta(hours=10),
            ),
        )
        for offset, signal_type, severity in (
            (30, "follow_up_overdue", 5),
            (30, "unowned_deal", 4),
            (54, "missing_next_step", 3),
        ):
            event = uuid4()
            run(
                "insert into public.commercial_events(id,tenant_id,event_type,producer,aggregate_type,aggregate_id,correlation_id,source,occurred_at,payload_hash) values(%s,%s,'deal.updated','test','deal','x',%s,'crm',%s,'h')",
                (event, self.tenant, self.correlation, now - timedelta(hours=offset)),
            )
            run(
                "insert into public.signals(tenant_id,event_id,opportunity_id,signal_type,rule_id,rule_version,severity,correlation_id,detected_at) values(%s,%s,%s,%s,'r','1',%s,%s,%s)",
                (
                    self.tenant,
                    event,
                    a,
                    signal_type,
                    severity,
                    self.correlation,
                    now - timedelta(hours=offset),
                ),
            )
        run(
            "insert into public.outcomes(tenant_id,intervention_id,opportunity_id,correlation_id,state_after_ref,result_type,sale_value,ares_influenced_value,incremental_value,currency,attribution_level,actor_type,source,observed_at) values(%s,%s,%s,%s,%s,'recovered',2000,1200,null,'BRL','influenced','system','ares',%s)",
            (
                self.tenant,
                self.intervention,
                a,
                self.correlation,
                context,
                now - timedelta(hours=5),
            ),
        )
        run(
            "insert into public.outcomes(tenant_id,intervention_id,opportunity_id,correlation_id,state_after_ref,result_type,sale_value,currency,attribution_level,actor_type,source,observed_at) values(%s,%s,%s,%s,%s,'sale_observed',1000,'BRL','observed','system','ares',%s)",
            (
                self.tenant,
                self.intervention,
                self.opportunities["C"],
                self.correlation,
                context,
                now - timedelta(hours=4),
            ),
        )
        for _ in range(2):
            run_id = uuid4()
            run(
                "insert into public.agent_runs(id,tenant_id,opportunity_id,context_ref,correlation_id,agent_name,agent_version,prompt_hash,output_schema_version,generation_mode,status,started_at) values(%s,%s,%s,%s,%s,'triage','m3','h','v1','deterministic_fallback','degraded',%s)",
                (run_id, self.tenant, a, context, self.correlation, now - timedelta(hours=6)),
            )
        run(
            "insert into public.model_usage(tenant_id,run_id,status) values(%s,%s,'not_called')",
            (self.tenant, run_id),
        )

    def transition(self, opportunity: UUID, state: str, at: datetime) -> None:
        self.db.execute(
            "insert into public.opportunity_state_transitions(tenant_id,opportunity_id,from_state,to_state,reason,correlation_id,occurred_at) values(%s,%s,null,%s,'synthetic',%s,%s)",
            (self.tenant, opportunity, state, self.correlation, at),
        )

    def user(self, who: UUID, role: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=who, tenant_id=self.tenant, role=role)  # type: ignore[arg-type]


@pytest.fixture
def scene() -> Iterator[tuple[Fixture, CommandCenterService]]:
    url = os.environ["ARES_TEST_DATABASE_URL"]
    db = psycopg.connect(url, row_factory=dict_row)
    try:
        fixture = Fixture(db)

        class Injected(CommandCenterService):
            @contextmanager
            def db(self) -> Iterator[psycopg.Connection[Any]]:
                yield db

        service = Injected(url, ImpactService(url), "development")
        yield fixture, service
    finally:
        db.rollback()
        db.close()


def test_manager_reads_the_now_block(scene):
    fixture, service = scene
    result = service.summary(fixture.user(fixture.manager, "manager"), 30)
    summary = CommandCenterSummary.model_validate(result)
    now = summary.now
    assert (now.open_at_risk, now.critical, now.sla_overdue, now.sla_next_6h, now.sla_missing) == (
        4,
        2,
        1,
        1,
        1,
    )
    assert now.without_owner == 3 and now.awaiting_decision == 0
    assert now.approvals.pending == 1 and now.approvals.expiring_within_6h == 1
    assert (
        now.failed_actions.count == 1
        and now.failed_actions.items[0].correlation_id == fixture.correlation
    )
    assert now.failed_actions.items[0].action_kind == "create_task"
    assert (now.connections.total, now.connections.degraded) == (2, 1)
    assert now.queue[0].opportunity_id == fixture.opportunities["A"]
    assert now.queue[0].pending_approval_id is not None
    assert {item.opportunity_id for item in now.queue} == set(fixture.opportunities.values())
    assert now.queue[-1].opportunity_id == fixture.opportunities["D"]
    assert summary.scope.mode == "tenant" and summary.capabilities.approve is True
    assert summary.capabilities.assign is False and summary.capabilities.fix_connection is True
    [value] = now.value_at_risk
    assert (value.currency, value.count, value.missing, value.total) == (
        "BRL",
        4,
        1,
        Decimal("7000"),
    )
    assert summary.computed_at == summary.window.until
    assert summary.freshness_at is not None


def test_impact_parity_and_null_incremental(scene):
    fixture, service = scene
    result = service.summary(fixture.user(fixture.manager, "manager"), 30)
    since, until = result["window"]["since"], result["window"]["until"]
    expected = ImpactService(os.environ["ARES_TEST_DATABASE_URL"]).snapshot(
        fixture.db, fixture.tenant, since, until
    )
    assert result["impact"] == expected
    summary = CommandCenterSummary.model_validate(result)
    assert summary.impact.counts.at_risk == 4 and summary.impact.counts.worked == 1
    [amount] = summary.impact.amounts
    assert amount.incremental_value is None and amount.recovered == 1 and amount.sales_observed == 2
    assert amount.ares_influenced_value == Decimal("1200")
    assert summary.impact.ai_cost is not None
    assert summary.impact.ai_cost.measured_runs <= summary.impact.ai_cost.runs == 2
    assert summary.coverage.ai_measured_runs == 0 and summary.coverage.deals_with_value == 3


def test_funnel_trends_signals_heatmap_activity(scene):
    fixture, service = scene
    summary = CommandCenterSummary.model_validate(
        service.summary(fixture.user(fixture.manager, "manager"), 7)
    )
    funnel = summary.funnel
    assert funnel.cohort == 4
    assert [stage.state for stage in funnel.stages] == list(MAIN_PATH_STATES)
    assert [stage.reached for stage in funnel.stages] == [4, 2, 1, 1, 0, 0, 0]
    assert len(summary.trends.days) == 8
    totals = {series.key: sum(series.values) for series in summary.trends.series}
    assert totals == {"opened": 4, "worked": 1, "executed": 0, "failed": 1}
    assert summary.signals.total == 3 and summary.signals.without_opportunity == 0
    assert [t.signal_type for t in summary.signals.types] == [
        "follow_up_overdue",
        "unowned_deal",
        "missing_next_step",
    ]
    assert len(summary.signals.days) == 8
    assert len(summary.heatmap.cells) == 28 and sum(c.count for c in summary.heatmap.cells) == 3
    assert summary.heatmap.timezone == "UTC"
    items = summary.activity.items
    assert [item.occurred_at for item in items] == sorted(
        (item.occurred_at for item in items), reverse=True
    )
    assert all(item.correlation_id == fixture.correlation for item in items)
    assert {item.kind for item in items} >= {"state", "decision", "action", "outcome"}
    outcome = next(item for item in items if item.kind == "outcome" and item.label == "recovered")
    assert outcome.attribution_level == "influenced"
    assert summary.activity.truncated is False


def test_seller_scope_only_sees_own_opportunities(scene):
    fixture, service = scene
    summary = CommandCenterSummary.model_validate(
        service.summary(fixture.user(fixture.seller, "seller"), 30)
    )
    assert summary.scope.mode == "own" and summary.scope.owner_user_id == fixture.seller
    assert summary.now.open_at_risk == 1
    assert {item.opportunity_id for item in summary.now.queue} == {fixture.opportunities["B"]}
    assert summary.now.approvals.pending == 0 and summary.now.failed_actions.count == 0
    assert summary.now.connections.total == 2
    assert summary.impact.counts.at_risk == 1 and summary.impact.ai_cost is None
    assert summary.impact.definitions[-1].startswith("Custo de IA é medido por tenant")
    assert summary.coverage.ai_runs is None
    assert summary.capabilities.approve is False
    assert summary.funnel.cohort == 1 and summary.signals.total == 0


def test_denied_for_foreign_tenant_inactive_membership_and_revoked_module(scene):
    fixture, service = scene
    with pytest.raises(CommandCenterDenied):
        service.summary(
            fixture.user(fixture.manager, "manager").model_copy(update={"tenant_id": uuid4()}), 30
        )
    fixture.db.execute(
        "update public.memberships set active=false where tenant_id=%s and user_id=%s",
        (fixture.tenant, fixture.seller),
    )
    with pytest.raises(CommandCenterDenied):
        service.summary(fixture.user(fixture.seller, "seller"), 30)
    fixture.db.execute(
        "update public.tenant_entitlements set status='revoked' where tenant_id=%s",
        (fixture.tenant,),
    )
    with pytest.raises(CommandCenterDenied):
        service.summary(fixture.user(fixture.manager, "manager"), 30)


def test_dev_tenant_smoke_read_only():
    url = os.environ["ARES_TEST_DATABASE_URL"]
    tenant = UUID("20000000-0000-0000-0000-000000000001")
    with psycopg.connect(url) as db:
        row = db.execute(
            "select user_id from public.memberships where tenant_id=%s and active and role='admin' limit 1",
            (tenant,),
        ).fetchone()
    assert row
    user = AuthenticatedUser(user_id=row[0], tenant_id=tenant, role="admin")
    summary = CommandCenterSummary.model_validate(
        CommandCenterService(url, ImpactService(url), "development").summary(user, 30)
    )
    assert all(amount.incremental_value is None for amount in summary.impact.amounts)
    assert len(summary.funnel.stages) == 7 and len(summary.heatmap.cells) == 28
    assert summary.impact.ai_cost is not None
    assert summary.impact.ai_cost.measured_runs <= summary.impact.ai_cost.runs
