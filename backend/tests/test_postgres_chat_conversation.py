import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_postgres_agents
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from ares.chat.conversation import recent_turns
from ares.chat.search import OpportunitySearch
from ares.chat.service import ChatService
from ares.config import Settings

fixture = test_postgres_agents.fixture
pytestmark = test_postgres_agents.pytestmark


@pytest.fixture
def chat(fixture, monkeypatch):
    db, _, seed = fixture
    user, _ = seed()

    @contextmanager
    def connection(*args, **kwargs):
        yield db

    monkeypatch.setattr("ares.chat.service.psycopg.connect", connection)
    return db, user, ChatService(Settings(openai_api_key=SecretStr(""))), seed


def deal(db, user, title, value, stage="proposal", currency="BRL"):
    return db.execute(
        "insert into public.deals(tenant_id,title,value,currency,external_stage,status) "
        "values(%s,%s,%s,%s,%s,'open') returning id",
        (user.tenant_id, title, value, currency, stage),
    ).fetchone()["id"]


def send(service, user, question):
    prepared = service.prepare(user, None, question)
    # The fixture rolls everything back in one transaction; now() is constant in it.
    # Real requests use separate transactions. Give each test turn an actual timestamp.
    import psycopg

    with psycopg.connect(service.settings.database_url) as db:
        db.execute(
            "update public.messages set created_at=clock_timestamp() where id=%s", (prepared["id"],)
        )
    stream = "".join(service.stream(prepared))
    assert "event: done" in stream and "event: error" not in stream
    return prepared, service.history(user, None)["items"][-1]


def test_screenshot_sequence_finds_best_open_value_beyond_recent_sample(chat):
    db, user, service, _ = chat
    winner = deal(db, user, "Negociação principal", 90000, "negotiation")
    db.execute("update public.deals set updated_at=now()-interval '2 days' where id=%s", (winner,))
    deal(db, user, "Venda já ganha", 999999, "won")
    deal(db, user, "Negócio perdido", 888888, "lost")
    for i in range(110):
        deal(db, user, f"Negócio pequeno {i}", 100 + i)
    send(service, user, "quais oportunidades estão disponíveis?")
    prepared, row = send(service, user, "qual a melhor oportunidade que temos hoje")
    assert prepared["comparison"]
    assert "Negociação principal" in row["assistant_text"]
    assert "BRL 90.000,00" in row["assistant_text"]
    assert "maior valor entre negócios abertos" in row["assistant_text"]
    assert "não significa maior chance" in row["assistant_text"]
    assert "Venda já ganha" not in row["assistant_text"]
    assert "Negócio perdido" not in row["assistant_text"]


def test_followup_revalidates_previous_list_and_does_not_expand_it(chat):
    db, user, service, _ = chat
    first = deal(db, user, "Alfa", 100)
    deal(db, user, "Beta", 200)
    send(service, user, "quais oportunidades estão disponíveis?")
    db.execute("update public.deals set value=300 where id=%s", (first,))
    deal(db, user, "Novo fora da lista", 999999)
    _, row = send(service, user, "e qual dessas tem maior valor?")
    assert "Alfa" in row["assistant_text"] and "BRL 300,00" in row["assistant_text"]
    assert "Novo fora da lista" not in row["assistant_text"]
    assert row["context_json"]["conversation_reference"]["record_references"]
    assert json.loads(row["context_json"]["content"])["selection"] == str(first)
    db.execute("update public.deals set is_missing=true where id=%s", (first,))
    _, row = send(service, user, "e dessa, qual o maior valor?")
    assert "Alfa" not in row["assistant_text"]
    assert not json.loads(row["context_json"]["content"])["matches"]


def test_history_references_are_private_to_owner_tenant_and_scope(chat):
    db, user, service, seed = chat
    deal(db, user, "Somente nesta conversa", 50)
    send(service, user, "quais oportunidades estão disponíveis?")
    other, _ = seed()
    assert recent_turns(service.settings.database_url, other, None) == []
    assert recent_turns(service.settings.database_url, user, uuid4()) == []
    actor = uuid4()
    db.execute("insert into auth.users(id) values(%s)", (actor,))
    db.execute(
        "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'manager')",
        (user.tenant_id, actor),
    )
    same_company = user.model_copy(update={"user_id": actor})
    assert recent_turns(service.settings.database_url, same_company, None) == []


def test_priority_zero_is_urgent_but_does_not_claim_sales_probability(chat):
    db, user, service, _ = chat
    critical = deal(db, user, "Precisa de atenção", 100)
    expensive = deal(db, user, "Maior contrato", 999999)
    for id_, priority in [(critical, 0), (expensive, 3)]:
        db.execute(
            "insert into public.ares_opportunities"
            "(tenant_id,deal_id,opportunity_type,state,priority,score) "
            "values(%s,%s,'revenue_recovery','prioritized',%s,0.9)",
            (user.tenant_id, id_, priority),
        )
    _, row = send(service, user, "qual oportunidade devo priorizar?")
    assert row["assistant_text"].startswith("Para **prioridade")
    assert "**Precisa de atenção**" in row["assistant_text"]
    assert "não chance de fechamento" in row["assistant_text"]


def test_mixed_currencies_and_zero_values_are_not_silently_compared(chat):
    db, user, service, _ = chat
    for i in range(12):
        deal(db, user, f"USD {i}", 100000 + i, currency="USD")
    deal(db, user, "Real zero", 0, currency="BRL")
    _, row = send(service, user, "qual a melhor oportunidade?")
    payload = json.loads(row["context_json"]["content"])
    assert set(payload["currencies"]) == {"BRL", "USD"}
    assert "selection" not in payload
    assert "moedas diferentes" in row["assistant_text"]
    assert "BRL 0,00" in row["assistant_text"]


def test_chat_uses_synced_mirror_without_claiming_live_crm_completeness(chat, monkeypatch):
    db, user, service, _ = chat
    id_ = deal(db, user, "Espelho antigo", 500)
    connection = uuid4()
    db.execute(
        "insert into public.connections(id,tenant_id,provider,status) "
        "values(%s,%s,'fake-crm-http','configured')",
        (connection, user.tenant_id),
    )
    db.execute(
        "update public.deals set connection_id=%s,external_id=%s,external_ref=%s where id=%s",
        (
            connection,
            f"{connection}:deal-live",
            Jsonb({"id": "deal-live", "provider": "fake-crm-http"}),
            id_,
        ),
    )
    legacy = deal(db, user, "Outra projeção do mesmo negócio", 999)
    db.execute(
        "update public.deals set external_id='deal-live',external_ref=%s where id=%s",
        (Jsonb({"id": "deal-live", "provider": "fake-crm"}), legacy),
    )
    live = SimpleNamespace(
        id="deal-live",
        title="Fonte atual",
        stage="won",
        value=90000,
        currency="BRL",
        changed_at=None,
    )

    class CRM:
        def __init__(self, *args):
            pass

        def list_deals(self, **kwargs):
            return SimpleNamespace(items=[live], next_cursor=None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Commercial totals must not consult partial live CRM pages")

    monkeypatch.setattr("ares.connectors.resolver.TenantCRMProvider.list_deals", forbidden)
    db.execute("update public.deals set connection_id=%s where id=%s", (connection, legacy))
    db.execute("update public.deals set external_stage='won' where id=%s", (id_,))
    search = OpportunitySearch(service.settings)
    assert not json.loads(search.read(user, "qual a melhor oportunidade?")["content"])["matches"]
    assert not json.loads(search.read(user, "oportunidades em proposta")["content"])["matches"]
    db.execute(
        "update public.deals set external_stage='proposal',value=400,"
        "title='Fonte atual' where id=%s",
        (id_,),
    )
    result = search.read(user, "qual a melhor oportunidade?")
    payload = json.loads(result["content"])
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["id"] == str(id_)
    assert result["result"]["metrics"]["duplicate_rows"] == 1
    assert str(payload["matches"][0]["value"]) == "400.00"
    assert payload["matches"][0]["title"] == "Fonte atual"
    assert not result["metadata"]["crm_sync_complete"]


def test_model_followup_receives_private_requests_and_fresh_selected_facts(chat, monkeypatch):
    db, user, service, _ = chat
    deal(db, user, "Alfa", 100)
    beta = deal(db, user, "Beta", 200)
    send(service, user, "qual a melhor oportunidade?")
    db.execute("update public.deals set value=350 where id=%s", (beta,))
    deal(db, user, "Novo fora da conversa", 999999)
    service.settings = service.settings.model_copy(
        update={"openai_api_key": SecretStr("synthetic")}
    )
    monkeypatch.setattr(
        "ares.chat.service.AIBudgetGuard.reserve", lambda *args: SimpleNamespace(allowed=True)
    )
    seen = {}

    class Agent:
        def __init__(self, **kwargs):
            assert kwargs["tools"] == []

        def run(self, question, **kwargs):
            snapshot = json.loads(question)
            seen["question"] = json.loads(snapshot["request"])
            seen["facts"] = snapshot["snapshot"]
            assert not any(
                item.get("title") == "Novo fora da conversa" for item in seen["facts"]["matches"]
            )
            yield SimpleNamespace(
                event="RunContent", content="Beta tem valor atualizado de BRL 350,00."
            )
            yield SimpleNamespace(event="RunCompleted", metrics=None)

    monkeypatch.setattr("ares.chat.service.Agent", Agent)
    _, row = send(service, user, "e por que essa foi escolhida?")
    assert seen["question"]["current_request"] == "e por que essa foi escolhida?"
    assert seen["question"]["previous_user_requests"] == ["qual a melhor oportunidade?"]
    assert seen["question"]["conversation_reference"]["selected_record_reference"] == str(beta)
    assert seen["question"]["conversation_reference"]["previous_criterion"] == "value"
    assert len(seen["facts"]["matches"]) == 2
    selected = next(item for item in seen["facts"]["matches"] if item["id"] == str(beta))
    assert str(selected["value"]) == "350.00"
    assert "BRL 350,00" in row["assistant_text"]


def test_supervisor_prepares_freeform_context_without_model_retrieval(chat, monkeypatch):
    db, user, service, seed = chat
    id_ = deal(db, user, "Contrato Alfa", 700)
    other, _ = seed()
    deal(db, other, "Contrato de outra empresa", 999999)
    service.settings = service.settings.model_copy(
        update={"openai_api_key": SecretStr("synthetic")}
    )
    monkeypatch.setattr(
        "ares.chat.service.AIBudgetGuard.reserve", lambda *args: SimpleNamespace(allowed=True)
    )
    seen = {}

    class Agent:
        def __init__(self, **kwargs):
            assert kwargs["tools"] == [] and kwargs["tool_call_limit"] == 0

        def run(self, question, **kwargs):
            seen["fresh"] = json.loads(question)["snapshot"]
            yield SimpleNamespace(
                event="RunContent",
                content="Contrato Alfa: BRL 700,00. Deseja analisar por valor ou urgência?",
            )
            yield SimpleNamespace(event="RunCompleted", metrics=None)

    monkeypatch.setattr("ares.chat.service.Agent", Agent)
    prepared, row = send(service, user, "Onde concentro meus esforços comerciais nesta semana?")
    assert "model_input" in prepared
    assert str(id_) in [item.get("id") for item in seen["fresh"]["matches"]]
    assert not any(
        item.get("title") == "Contrato de outra empresa" for item in seen["fresh"]["matches"]
    )
    assert "Contrato de outra empresa" not in row["assistant_text"]
    assert row["context_json"]["metadata"]["query"]["name"] is None
    assert row["tool_calls_json"] == [{"name": "context_builder", "status": "completed"}]
