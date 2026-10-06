import json
from uuid import uuid4

from pydantic import SecretStr

from ares.auth.models import AuthenticatedUser
from ares.chat.conversation import conversation_reference
from ares.chat.search import comparison_criterion, make_context, search_terms
from ares.chat.service import ChatService, comparison_answer, general_answer, is_general_discovery
from ares.config import Settings


def test_general_opportunity_request_has_no_name_filter():
    assert search_terms("qual a melhor oportunidade que temos hoje") == []
    assert comparison_criterion("qual a melhor oportunidade que temos hoje") == "value"
    assert comparison_criterion("quais são as mais urgentes?") == "urgency"
    assert comparison_criterion("qual a melhor estratégia para essas oportunidades?") is None
    assert comparison_criterion("qual tem maior chance de fechamento?") is None
    assert search_terms("busque a oportunidade com nome Melhor Mercado") == ["melhor", "mercado"]
    assert comparison_criterion("busque a oportunidade com nome Melhor Mercado") is None
    assert search_terms("me dê alguns dados sobre as oportunidades disponíveis") == []
    assert search_terms("descreva as oportunidades disponíveis") == []
    assert search_terms("qual a oportunidade temos hoje") == []
    assert (
        search_terms(
            "Quais oportunidades estão disponíveis? Traga os nomes, etapas e valores salvos."
        )
        == []
    )
    assert search_terms("mostre a oportunidade com nome Demonstração Alfa") == [
        "demonstracao",
        "alfa",
    ]
    assert search_terms("quais oportunidades estão em negociação?") == ["negociacao"]
    assert search_terms("mostre a oportunidade Demonstração Alfa") == ["demonstracao", "alfa"]
    assert is_general_discovery("qual a oportunidade temos hoje")
    assert is_general_discovery("me dê informações sobre oportunidades")
    assert is_general_discovery("descreva as oportunidades disponíveis")
    assert is_general_discovery("quais oportunidades estão em negociação?")
    assert not is_general_discovery("mostre a oportunidade Demonstração Alfa")
    assert not is_general_discovery("quais são os riscos das oportunidades?")
    assert not is_general_discovery("qual oportunidade tem maior valor?")


def test_general_answer_displays_only_returned_records_and_limits():
    context = make_context(
        {
            "matches": [
                {
                    "title": "Demonstração Alfa",
                    "external_stage": "proposta",
                    "value": "12500.00",
                    "currency": "BRL",
                    "source": "Banco ARES (espelho do CRM)",
                }
            ],
            "limitations": ["CRM indisponível nesta consulta."],
        },
        source="Banco ARES",
        truncated=True,
    )
    answer = general_answer(context)
    assert "Demonstração Alfa" in answer
    assert "BRL 12.500,00" in answer
    assert "CRM indisponível" in answer
    assert "total do funil" in answer
    assert json.loads(context["content"])["matches"][0]["title"] in answer


def test_references_resolve_ordinals_and_selection_without_reusing_old_facts():
    rows = [{"id": "first", "title": "Primeira"}, {"id": "second", "title": "Segunda"}]
    context = make_context({"matches": rows, "selection": "second"})
    turns = [{"user_text": "qual a melhor oportunidade?", "context_json": context}]
    assert conversation_reference(turns, "e qual dessas tem maior valor?")[0] == ["first", "second"]
    assert conversation_reference(turns, "qual é a primeira?")[0] == ["first"]
    assert conversation_reference(turns, "e essa, qual é o valor dela?")[0] == ["second"]
    assert conversation_reference(turns, "e a terceira?")[0] == []
    assert conversation_reference(turns, "qual a melhor oportunidade hoje?")[0] is None
    assert conversation_reference([], "e dessas?")[0] is None
    continuation = make_context({"matches": rows})
    continuation["conversation_reference"] = {
        "selected_record_reference": "second",
        "previous_criterion": "value",
    }
    assert conversation_reference(
        [{"user_text": "por que essa?", "context_json": continuation}], "e qual é o valor dela?"
    )[0] == ["second"]


def test_comparison_explains_criterion_currency_missing_values_and_zero():
    def answer(matches, criterion="value"):
        return comparison_answer(
            make_context({"matches": matches, "criterion": criterion}),
            "qual a melhor oportunidade?",
        )

    row = {"title": "Alfa", "value": 0, "currency": "BRL", "external_stage": "proposal"}
    assert "BRL 0,00" in answer([row])
    assert "Proposta" in answer([row])
    assert "não significa maior chance" in answer([row])
    assert "faltam valores" in answer([{**row, "value": None}])
    assert "moedas diferentes" in answer([row, {**row, "currency": "USD", "value": 999}])
    assert "não chance de fechamento" in answer([{**row, "priority": 0}], "urgency")


def test_empty_retrieval_never_calls_the_model(monkeypatch):
    from ares.chat import service as chat_service

    class Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args):
            return None

    context = make_context({"matches": [], "limitations": ["CRM indisponível nesta consulta."]})
    user = AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role="manager")
    observations = []
    monkeypatch.setattr(chat_service.OpportunitySearch, "read", lambda *_args: context)
    monkeypatch.setattr(chat_service.psycopg, "connect", lambda *_args, **_kwargs: Db())
    monkeypatch.setattr(chat_service, "record_usage", lambda *_args: observations.append(_args[-1]))
    monkeypatch.setattr(
        chat_service,
        "Agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )
    prepared = {
        "context": make_context(),
        "user": user,
        "scope": None,
        "text": "Descreva a oportunidade inexistente",
        "id": uuid4(),
        "run_id": uuid4(),
        "correlation_id": uuid4(),
    }
    events = list(ChatService(Settings()).stream(prepared))
    assert any("CRM indisponível" in event for event in events)
    assert any("event: done" in event for event in events)
    assert observations[0].status == "not_called"


def test_empty_retrieval_passes_preflight_without_model_or_quota(monkeypatch):
    from ares.chat import service as chat_service

    class Result:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

        def fetchall(self):
            return []

    class Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, *_args):
            if "insert into public.conversations" in query:
                return Result({"id": uuid4()})
            return Result()

    empty = make_context({"matches": [], "limitations": []})
    monkeypatch.setattr(chat_service.ChatService, "empty_context", lambda *_args: make_context())
    monkeypatch.setattr(chat_service.OpportunitySearch, "read", lambda *_args: empty)
    monkeypatch.setattr(chat_service.psycopg, "connect", lambda *_args, **_kwargs: Db())
    monkeypatch.setattr(
        chat_service.AIBudgetGuard,
        "reserve",
        lambda *_args: (_ for _ in ()).throw(AssertionError("quota reserved")),
    )
    user = AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role="manager")
    prepared = ChatService(Settings(openai_api_key=SecretStr(""))).prepare(
        user, None, "descreva o caso inexistente"
    )
    assert prepared["retrieved"] is True
    assert json.loads(prepared["context"]["content"])["matches"] == []
