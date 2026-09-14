import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import test_postgres_agents
from psycopg.types.json import Jsonb
from pydantic import SecretStr

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
        "ares.chat.service.AIBudgetGuard.check", lambda *args: SimpleNamespace(allowed=True)
    )

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.chat.service.psycopg.connect", connection)

    class FakeAgent:
        def __init__(self, **kwargs):
            self.tools = kwargs["tools"]

        def run(self, *args, **kwargs):
            yield SimpleNamespace(event="ToolCallStarted")
            self.tools[0]()
            yield SimpleNamespace(event="ToolCallCompleted")
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
    assert len(history[0]["tool_calls_json"]) == 2
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
