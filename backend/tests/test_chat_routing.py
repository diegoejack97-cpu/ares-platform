import pytest
from pydantic import ValidationError

from ares.chat.api import ChatCommand, ChatFeedbackCommand
from ares.chat.routing import route_question


@pytest.mark.parametrize(
    "question,route",
    [
        ("Como funciona o sistema?", "help"),
        ("O que faço agora?", "recommendation"),
        ("Qual o valor total?", "commercial_query"),
        ("Compare essas oportunidades", "prioritization"),
        ("Onde agir agora?", "prioritization"),
        ("Quais têm o prazo mais próximo?", "prioritization"),
        ("Quais são mais atrativas?", "prioritization"),
        ("Qual o risco dessa?", "diagnosis"),
        ("O que mudou?", "diagnosis"),
    ],
)
def test_controlled_purposes(question, route):
    assert route_question(question) == route


def test_browser_cannot_supply_evidence_or_feedback_run():
    with pytest.raises(ValidationError):
        ChatCommand(text="Explique", evidence={"fake": "fact"})
    with pytest.raises(ValidationError):
        ChatFeedbackCommand(rating="helpful", run_id="fake")
