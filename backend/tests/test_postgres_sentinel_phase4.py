"""Real PostgreSQL acceptance for rules, lifecycle, inbox and interpretation."""

# ruff: noqa: E501
import json
from uuid import uuid4

import pytest
import test_postgres_agent_runtime as base

from ares.agents.executor import AgentOutcome, AgnoExecutor
from ares.agents.specialists import DiagnosisAnalysis, FactClaim
from ares.ai.usage import UsageObservation
from ares.auth.models import AuthenticatedUser
from ares.sentinels.interpreter import SentinelInterpreter
from ares.sentinels.models import SentinelRuleCommand
from ares.sentinels.notifications import NotificationService
from ares.sentinels.service import RULE_ID, SentinelScheduleConflict, SentinelService

fixture = base.fixture
query = base.query
pytestmark = base.pytestmark


@pytest.fixture
def scenario(fixture):
    runtime, user, opportunity, _, _, seller = fixture
    deal = uuid4()
    query(
        fixture,
        "insert into public.deals(id,tenant_id,title,value,currency,canonical_stage) values(%s,%s,'Synthetic Phase4',0,'BRL','proposal')",
        (deal, user.tenant_id),
    )
    query(
        fixture,
        "update public.ares_opportunities set deal_id=%s,sla_at='2000-01-01',owner_user_id=%s where id=%s",
        (deal, seller, opportunity),
    )
    query(
        fixture,
        "update public.sentinel_schedules set next_run_at='1900-01-01' where tenant_id=%s",
        (user.tenant_id,),
    )
    yield fixture
    for table in ["model_usage", "ai_usage_ledger", "ai_budget_reservations", "agent_runs"]:
        query(fixture, f"delete from public.{table} where tenant_id=%s", (user.tenant_id,))
    query(fixture, "delete from public.sentinel_findings where tenant_id=%s", (user.tenant_id,))
    query(
        fixture,
        "update public.ares_opportunities set deal_id=null where tenant_id=%s",
        (user.tenant_id,),
    )
    query(fixture, "delete from public.deals where tenant_id=%s", (user.tenant_id,))


def scan(scenario):
    query(
        scenario,
        "update public.sentinel_schedules set next_run_at='1900-01-01' where tenant_id=%s",
        (scenario[1].tenant_id,),
    )
    return SentinelService(base.URL).scan_sync()


def test_lifecycle_dedupe_personal_read_and_reassignment(scenario):
    _, user, opportunity, _, _, seller = scenario
    inbox = NotificationService(base.URL)
    scan(scenario)
    first = inbox.list_sync(user)
    assert first["total"] == first["unread_count"] == 1
    finding = first["items"][0]
    inbox.mark_sync(user, finding["id"], finding["revision"], "archive")
    assert inbox.list_sync(user)["unread_count"] == 0
    scan(scenario)
    assert inbox.list_sync(user, view="archived")["total"] == 1
    query(scenario, "update public.ares_opportunities set score=0.9 where id=%s", (opportunity,))
    scan(scenario)
    updated = inbox.list_sync(user)["items"][0]
    assert (
        updated["id"] == finding["id"]
        and updated["revision"] == 2
        and updated["status"] == "updated"
    )
    assert inbox.list_sync(user)["unread_count"] == 1
    with pytest.raises(SentinelScheduleConflict, match="stale_sentinel_finding"):
        inbox.mark_sync(user, finding["id"], 1, "read")
    seller_user = AuthenticatedUser(user_id=seller, tenant_id=user.tenant_id, role="admin")
    assert inbox.list_sync(seller_user)["total"] == 1
    query(
        scenario,
        "update public.ares_opportunities set owner_user_id=%s where id=%s",
        (user.user_id, opportunity),
    )
    assert inbox.list_sync(seller_user)["total"] == 0
    with pytest.raises(SentinelScheduleConflict, match="sentinel_finding_not_found"):
        inbox.mark_sync(seller_user, finding["id"], 2, "read")
    query(
        scenario, "update public.ares_opportunities set state='closed' where id=%s", (opportunity,)
    )
    scan(scenario)
    assert inbox.list_sync(user)["items"][0]["status"] == "resolved"
    assert (
        len(
            query(
                scenario,
                "select 1 from public.sentinel_finding_events where finding_id=%s",
                (finding["id"],),
            )
        )
        == 3
    )
    query(
        scenario,
        "update public.memberships set active=false where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    with pytest.raises(SentinelScheduleConflict, match="sentinel_access_denied"):
        inbox.list_sync(user)


def test_typed_filters_preview_capacity_and_pagination(scenario):
    _, user, opportunity, *_ = scenario
    service = SentinelService(base.URL)
    command = SentinelRuleCommand(
        title="Synthetic BRL rule",
        kind="sla_overdue",
        threshold_hours=0,
        enabled=True,
        interval_minutes=1440,
        start_time_local="00:00",
        reason="Synthetic criteria",
        criteria={"stages": ["proposal"], "currency": "BRL", "min_value": 0, "max_value": 0},
    )
    result = service.preview_sync(user, command)
    assert result["matched_count"] == 1 and not result["ai_called"]
    assert not query(
        scenario, "select 1 from public.sentinel_findings where tenant_id=%s", (user.tenant_id,)
    )
    saved = service.save_rule_sync(user.tenant_id, user.user_id, command)
    scan(scenario)
    inbox = NotificationService(base.URL)
    page = inbox.list_sync(user, limit=1)
    assert page["total"] == 2 and page["unread_count"] == 2 and page["next_offset"] == 1
    second = inbox.list_sync(user, limit=1, offset=1)
    assert second["unread_count"] == 2 and second["items"][0]["id"] != page["items"][0]["id"]
    query(scenario, "update public.deals set currency='USD' where tenant_id=%s", (user.tenant_id,))
    scan(scenario)
    assert (
        next(
            item for item in inbox.list_sync(user)["items"] if item["rule_id"] == saved["rule_id"]
        )["status"]
        == "resolved"
    )
    query(
        scenario,
        "update public.tenant_quotas set sentinel_slots=0 where tenant_id=%s",
        (user.tenant_id,),
    )
    with pytest.raises(SentinelScheduleConflict, match="sentinel_capacity_unavailable"):
        service.preview_sync(user, command)


class Interpreter:
    calls = 0
    invalid = False

    async def execute(self, definition, payload, model):
        self.calls += 1
        assert definition.agent_id == "sentinel-interpreter"
        return AgentOutcome(
            DiagnosisAnalysis(
                summary="Condição de risco exige revisão humana.",
                facts=[
                    FactClaim(
                        path="/finding/value",
                        value="999"
                        if self.invalid
                        else json.loads(payload.content)["finding"]["value"],
                    )
                ],
                hypotheses=[],
                evidence_refs=payload.evidence_refs,
                limitations=[],
                needs_human_review=True,
            ),
            UsageObservation(status="not_called"),
        )


@pytest.mark.parametrize("mode", ["success", "missing", "invalid", "revoked", "uncertain"])
def test_interpreter_preserves_finding_without_duplicate_calls(scenario, mode):
    _, user, *_ = scenario
    query(
        scenario,
        "update public.sentinel_schedules set interpret_with_ai=true where tenant_id=%s and rule_id=%s",
        (user.tenant_id, RULE_ID),
    )
    scan(scenario)
    job = query(
        scenario,
        "select payload from public.jobs where tenant_id=%s and kind='sentinel.interpret'",
        (user.tenant_id,),
    )[0]["payload"]
    executor = Interpreter()
    executor.invalid = mode == "invalid"
    if mode == "revoked":
        query(
            scenario,
            "update public.sentinel_schedules set enabled=false where tenant_id=%s",
            (user.tenant_id,),
        )
    interpreter = SentinelInterpreter(
        base.URL, "gpt-5.4", executor=AgnoExecutor("") if mode == "missing" else executor
    )
    if mode == "uncertain":
        run = uuid4()
        query(
            scenario,
            "insert into public.agent_runs(id,tenant_id,opportunity_id,agent_name,agent_version,prompt_hash,output_schema_version,generation_mode,status,correlation_id,sentinel_context_ref) values(%s,%s,%s,'sentinel-interpreter','test','test','diagnosis-output.v1','agno_openai','running',%s,%s)",
            (run, user.tenant_id, scenario[2], uuid4(), job["context_ref"]),
        )
        query(
            scenario,
            "update public.sentinel_findings set interpretation_status='running',interpretation_run_id=%s where id=%s",
            (run, job["finding_id"]),
        )
    interpreter.process(user.tenant_id, job)
    interpreter.process(user.tenant_id, job)
    finding = NotificationService(base.URL).list_sync(user)["items"][0]
    assert finding["status"] == "open"
    assert (
        finding["interpretation_status"]
        == {
            "success": "ready",
            "missing": "degraded",
            "invalid": "failed",
            "revoked": "degraded",
            "uncertain": "failed",
        }[mode]
    )
    assert executor.calls == (1 if mode in {"success", "invalid"} else 0)
