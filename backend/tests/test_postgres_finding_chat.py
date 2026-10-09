"""Acceptance: personal handoff, current facts, ownership, history and feedback."""

# ruff: noqa: E501
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
import test_postgres_agent_runtime as base
import test_postgres_sentinel_phase4 as phase4
from pydantic import SecretStr

from ares.auth.models import AuthenticatedUser
from ares.chat.handoff import FindingChat
from ares.chat.service import ChatFailure, ChatService
from ares.config import Settings
from ares.sentinels.notifications import NotificationService

fixture = phase4.fixture
scenario = phase4.scenario
query = phase4.query
scan = phase4.scan

pytestmark = base.pytestmark


@pytest.fixture
def chat_case(scenario):
    scan(scenario)
    finding = NotificationService(base.URL).list_sync(scenario[1])["items"][0]["id"]
    yield scenario, UUID(str(finding))
    tenant = scenario[1].tenant_id
    for table in ("chat_feedback", "sentinel_chat_openings", "messages", "conversations"):
        query(scenario, f"delete from public.{table} where tenant_id=%s", (tenant,))


def test_parallel_opening_reuses_personal_thread_without_model_calls(chat_case):
    case, finding = chat_case
    user = case[1]
    bridge = FindingChat(base.URL)
    with ThreadPoolExecutor(max_workers=2) as pool:
        opened = list(pool.map(lambda _: bridge.open(user, finding), range(2)))
    assert opened[0]["conversation_id"] == opened[1]["conversation_id"]
    assert sorted(item["reused"] for item in opened) == [False, True]
    assert (
        query(case, "select count(*) n from public.messages where tenant_id=%s", (user.tenant_id,))[
            0
        ]["n"]
        == 1
    )
    assert (
        query(
            case, "select count(*) n from public.model_usage where tenant_id=%s", (user.tenant_id,)
        )[0]["n"]
        == 0
    )
    history = ChatService(Settings(database_url=base.URL, openai_api_key=SecretStr(""))).history(
        user, None, finding
    )
    assert history["finding"]["condition_current"]
    assert "continua presente" in history["items"][0]["assistant_text"]


def test_followups_requery_current_state_and_preserve_original_detection(chat_case):
    case, finding = chat_case
    user = case[1]
    bridge = FindingChat(base.URL)
    bridge.open(user, finding)
    chat = ChatService(Settings(database_url=base.URL, openai_api_key=SecretStr("")))
    for question in ("Por que essa oportunidade exige atenção?", "O que faço agora?"):
        prepared = chat.prepare(user, None, question, finding)
        assert "event: done" in "".join(chat.stream(prepared))
    query(case, "update public.ares_opportunities set state='closed' where id=%s", (case[2],))
    prepared = chat.prepare(user, None, "O que mudou desde o alerta?", finding)
    assert "não está mais ativa" in "".join(chat.stream(prepared))
    history = chat.history(user, None, finding)
    assert history["finding"]["changed"] and not history["finding"]["condition_current"]
    assert len(history["items"]) == 4
    assert history["items"][0]["context_json"]["finding_origin"]["condition_current"]
    assert bridge.open(user, finding)["reused"] is False
    assert bridge.open(user, finding)["reused"] is True
    assert len(chat.history(user, None, finding)["items"]) == 5


def test_seller_handoff_revokes_on_reassignment_and_other_tenant_is_denied(chat_case):
    case, finding = chat_case
    admin, seller = case[1], case[5]
    user = AuthenticatedUser(
        user_id=seller, tenant_id=admin.tenant_id, role="seller", email="synthetic@example.invalid"
    )
    FindingChat(base.URL).open(user, finding)
    chat = ChatService(Settings(database_url=base.URL, openai_api_key=SecretStr("")))
    assert len(chat.history(user, None, finding)["items"]) == 1
    foreign = AuthenticatedUser(
        user_id=seller, tenant_id=uuid4(), role="admin", email="synthetic@example.invalid"
    )
    with pytest.raises(ChatFailure):
        FindingChat(base.URL).open(foreign, finding)
    prepared = chat.prepare(user, None, "Qual o risco dessa?", finding)
    query(
        case,
        "update public.ares_opportunities set owner_user_id=%s where id=%s",
        (admin.user_id, case[2]),
    )
    assert "event: error" in "".join(chat.stream(prepared))
    with pytest.raises(ChatFailure):
        chat.history(user, None, finding)


def test_history_cursor_and_feedback_are_owned_and_linked(chat_case):
    case, finding = chat_case
    user = case[1]
    bridge = FindingChat(base.URL)
    bridge.open(user, finding)
    original = query(case, "select * from public.messages where tenant_id=%s", (user.tenant_id,))[0]
    for _ in range(35):
        query(
            case,
            "insert into public.messages(tenant_id,conversation_id,run_id,user_text,assistant_text,status,context_json) values(%s,%s,%s,'Synthetic question','Synthetic answer','succeeded',%s)",
            (
                user.tenant_id,
                original["conversation_id"],
                original["run_id"],
                base.Jsonb(original["context_json"]),
            ),
        )
    chat = ChatService(Settings(database_url=base.URL, openai_api_key=SecretStr("")))
    page = chat.history(user, None, finding)
    older = chat.history(user, None, finding, UUID(page["next_before"]))
    assert len(page["items"]) == 30 and len(older["items"]) == 6
    assert not set(item["id"] for item in page["items"]) & set(
        item["id"] for item in older["items"]
    )
    bridge.feedback(user, original["id"], "unhelpful", "Synthetic missing context")
    feedback = query(
        case, "select * from public.chat_feedback where tenant_id=%s", (user.tenant_id,)
    )[0]
    assert feedback["run_id"] == original["run_id"]
    assert feedback["context_ref"] == original["context_json"]["context_ref"]
    with pytest.raises(ChatFailure):
        chat.history(user, None, finding, uuid4())
    seller = AuthenticatedUser(
        user_id=case[5], tenant_id=user.tenant_id, role="seller", email="synthetic@example.invalid"
    )
    with pytest.raises(ChatFailure):
        bridge.feedback(seller, original["id"], "helpful", "")
