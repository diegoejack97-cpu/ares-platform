import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import test_postgres_agents
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from ares.chat.search import OpportunitySearch, make_context
from ares.chat.service import ChatFailure, ChatService
from ares.config import Settings

fixture = test_postgres_agents.fixture
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


def test_scoped_chat_stream_persists_tools_usage_and_history(fixture, monkeypatch):
    db, _, seed = fixture
    user, _ = seed()
    other, _ = seed()
    row = db.execute(
        "select id,opportunity_id from public.context_snapshots where tenant_id=%s",
        (user.tenant_id,),
    ).fetchone()
    context = {
        "context_ref": str(row["id"]),
        "content": '{"events":[]}',
        "content_hash": "test",
        "captured_at": datetime.now(UTC),
        "tokens_upper_bound": 13,
        "token_limit": 2500,
        "citations": [],
        "count_method": "utf8_bytes_upper_bound",
        "truncated": False,
        "source": "Event Journal",
    }
    service = ChatService(Settings(openai_api_key=SecretStr("synthetic")))
    monkeypatch.setattr(service, "context", lambda *args: context)
    monkeypatch.setattr(
        "ares.chat.service.AIBudgetGuard.reserve", lambda *args: SimpleNamespace(allowed=True)
    )

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.chat.service.psycopg.connect", connection)

    class FakeAgent:
        def __init__(self, **kwargs):
            assert kwargs["tools"] == [] and kwargs["tool_call_limit"] == 0

        def run(self, *args, **kwargs):
            assert "snapshot" in json.loads(args[0])
            yield SimpleNamespace(event="RunContent", content="Sem eventos neste recorte.")
            yield SimpleNamespace(
                event="RunCompleted",
                metrics=SimpleNamespace(
                    input_tokens=1000, output_tokens=200, cache_read_tokens=400
                ),
            )

    monkeypatch.setattr("ares.chat.service.Agent", FakeAgent)
    prepared = service.prepare(user, row["opportunity_id"], "Resuma")
    with pytest.raises(ChatFailure) as error:
        service.prepare(user, row["opportunity_id"], "Duplicada")
    assert error.value.status == 409
    stream = "".join(service.stream(prepared))
    assert "event: tool" in stream and "event: token" in stream and "event: done" in stream
    history = service.history(user, row["opportunity_id"])["items"]
    assert len(history) == 1 and history[0]["status"] == "succeeded"
    assert history[0]["tool_calls_json"] == [{"name": "context_builder", "status": "completed"}]
    assert service.history(other, row["opportunity_id"])["items"] == []
    assert (
        db.execute(
            "select count(*) n from public.model_usage where tenant_id=%s", (user.tenant_id,)
        ).fetchone()["n"]
        == 1
    )

    for viewer, expected in [(other, 0), (user, 1)]:
        db.execute(
            "select set_config('request.jwt.claims',%s::text,true)",
            (
                Jsonb(
                    {
                        "sub": str(viewer.user_id),
                        "role": "authenticated",
                        "app_metadata": {"active_tenant_id": str(viewer.tenant_id)},
                    }
                ),
            ),
        )
        db.execute("set local role authenticated")
        assert (
            db.execute(
                "select count(*) n from public.messages where tenant_id=%s", (user.tenant_id,)
            ).fetchone()["n"]
            == expected
        )
        assert (
            db.execute(
                "select count(*) n from public.model_usage where tenant_id=%s", (user.tenant_id,)
            ).fetchone()["n"]
            == expected
        )
        db.execute("reset role")


def test_missing_model_stops_before_creating_messages(fixture, monkeypatch):
    _, _, seed = fixture
    user, _ = seed()
    service = ChatService(Settings(openai_api_key=SecretStr("")))
    monkeypatch.setattr(service, "context", lambda *args: {})
    with pytest.raises(ChatFailure) as error:
        service.prepare(user, user.tenant_id, "Resumo")
    assert error.value.code == "model_not_configured"


def test_unscoped_greeting_is_private_and_does_not_call_model(fixture, monkeypatch):
    db, _, seed = fixture
    user, _ = seed()
    other, _ = seed()
    service = ChatService(Settings(openai_api_key=SecretStr("")))

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.chat.service.psycopg.connect", connection)
    monkeypatch.setattr("ares.ai.usage.psycopg.connect", connection)
    prepared = service.prepare(user, None, "oi")
    stream = "".join(service.stream(prepared))
    assert "event: done" in stream
    assert "event: tool" not in stream
    assert service.history(user, None)["items"][-1]["assistant_text"].startswith("Olá!")
    assert service.history(other, None)["items"] == []
    usage = db.execute(
        "select status,model_id from public.model_usage where tenant_id=%s and run_id=%s",
        (user.tenant_id, prepared["run_id"]),
    ).fetchone()
    assert usage["status"] == "not_called" and usage["model_id"] is None


def test_general_question_returns_available_records_without_model(fixture, monkeypatch):
    db, _, seed = fixture
    user, _ = seed()
    other, _ = seed()
    deal_id = db.execute(
        "insert into public.deals(tenant_id,title,value,currency,external_stage) "
        "values(%s,'Demonstração Alfa',12500,'BRL','proposta') returning id",
        (user.tenant_id,),
    ).fetchone()["id"]
    db.execute(
        "insert into public.deals(tenant_id,title,value,currency,external_stage) "
        "values(%s,'Expansão Beta',8000,'BRL','negotiation')",
        (user.tenant_id,),
    )

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.chat.service.psycopg.connect", connection)
    monkeypatch.setattr("ares.intelligence.context_builder.psycopg.connect", connection)
    monkeypatch.setattr("ares.ai.usage.psycopg.connect", connection)
    service = ChatService(Settings(openai_api_key=SecretStr("")))
    prepared = service.prepare(user, None, "me dê alguns dados sobre as oportunidades disponíveis")
    stream = "".join(service.stream(prepared))
    assert "Demonstração Alfa" in stream
    assert "BRL 12.500,00" in stream
    assert "event: done" in stream
    assert service.history(user, None)["items"][-1]["status"] == "succeeded"
    assert service.history(other, None)["items"] == []
    prepared = service.prepare(user, None, "qual a oportunidade temos hoje")
    stream = "".join(service.stream(prepared))
    assert "Demonstração Alfa" in stream
    assert "event: done" in stream
    assert "event: error" not in stream
    usage = db.execute(
        "select status from public.model_usage where tenant_id=%s and run_id=%s",
        (user.tenant_id, prepared["run_id"]),
    ).fetchone()
    assert usage["status"] == "not_called"
    prepared = service.prepare(user, None, "quais oportunidades estão em negociação?")
    stream = "".join(service.stream(prepared))
    assert "Expansão Beta" in stream
    assert "Demonstração Alfa" not in stream
    assert "event: done" in stream
    context = OpportunitySearch(service.settings).read(user, "oportunidades em proposta")
    assert any(item["id"] == str(deal_id) for item in json.loads(context["content"])["matches"])


def test_unscoped_search_stream_persists_evidence_without_writing_crm(fixture, monkeypatch):
    db, _, seed = fixture
    user, _ = seed()
    service = ChatService(Settings(openai_api_key=SecretStr("synthetic")))
    found = make_context(
        {"matches": [{"title": "Oportunidade de teste", "source": "Banco ARES"}]},
        source="Banco ARES",
    )

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.chat.service.psycopg.connect", connection)
    monkeypatch.setattr("ares.chat.search.OpportunitySearch.read", lambda *args: found)
    monkeypatch.setattr(
        "ares.chat.service.AIBudgetGuard.reserve", lambda *args: SimpleNamespace(allowed=True)
    )

    class FakeAgent:
        def __init__(self, **kwargs):
            assert kwargs["tools"] == []

        def run(self, *args, **kwargs):
            assert "Oportunidade de teste" in args[0]
            yield SimpleNamespace(event="RunContent", content="Oportunidade de teste.")
            yield SimpleNamespace(event="RunCompleted", metrics=None)

    monkeypatch.setattr("ares.chat.service.Agent", FakeAgent)
    prepared = service.prepare(user, None, "Busque Oportunidade de teste")
    stream = "".join(service.stream(prepared))
    assert "event: status" in stream and "event: context" in stream
    assert "event: token" in stream and "event: done" in stream
    assert service.history(user, None)["items"][-1]["context_json"]["source"] == "Banco ARES"
