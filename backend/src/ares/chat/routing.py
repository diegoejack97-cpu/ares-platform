"""Bounded purpose routing; no model may choose a grant or CRM operation."""

import re

from ares.chat.search import comparison_criterion, normalize


def portfolio_criterion(question: str) -> str | None:
    words = normalize(question)
    if re.search(r"\b(prazo|prazos|vencimento|vencimentos)\b", words) and re.search(
        r"\b(proximo|proximos|mais perto|menor)\b", words
    ):
        return "deadline"
    if re.search(r"\b(atratividade|atrativas?|atrativos?)\b", words):
        return "attractiveness"
    if re.search(r"\b(onde agir|onde atuar)\b", words):
        return "urgency"
    return comparison_criterion(question)


def route_question(question: str) -> str:
    words = normalize(question)
    if re.search(r"\b(como funciona|para que serve|como usar|ajuda|funcionalidades)\b", words):
        return "help"
    if re.search(r"\b(o que faco|recomende|recomendacao|proximo passo|devo fazer)\b", words):
        return "recommendation"
    if portfolio_criterion(question) or re.search(r"\b(compare|comparar)\b", words):
        return "prioritization"
    if re.search(r"\b(quantas|quantos|total|soma|qual valor)\b", words):
        return "commercial_query"
    return "diagnosis"


def help_answer() -> str:
    return (
        "Você pode consultar negócios, valores e riscos no Chat ARES. "
        "O Radar apresenta oportunidades que exigem atenção; "
        "Sentinelas configura regras e agendas, "
        "e o sino guarda os achados. Abrir um alerta inicia uma conversa "
        "com sua origem e dados atuais.\n\n"
        "O Funil CRM mostra o espelho do CRM conectado. Mudanças exigem confirmação. "
        "Aprovações reúne propostas de intervenção e decisões autorizadas. "
        "Diagnósticos especializados dependem de ativação e capacidade do plano.\n\n"
        "O chat explica e orienta; uma mensagem não aprova nem executa uma ação no CRM."
    )
