"""Bounded read-only discovery over the tenant mirror and the configured CRM adapter."""

# Search clauses remain intact for comparison with the source schema.
# ruff: noqa: E501, SIM905

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from ares.auth.models import AuthenticatedUser
from ares.config import Settings

CONTEXT_LIMIT = 8000
RESULT_LIMIT = 8
CRM_PAGE_LIMIT = 5
STAGE_ALIASES = {
    "entrada": ("entrada", "new"),
    "ganho": ("ganho", "won"),
    "perdido": ("perdido", "lost"),
    "negociacao": ("negociacao", "negotiation"),
    "proposta": ("proposta", "proposal"),
    "qualificacao": ("qualificacao", "qualification"),
}
STOP_WORDS = set(
    "a as o os de da das do dos e em no na nos nas um uma uns umas para por com que qual quais "
    "quero gostaria preciso precisam pode poderia me mostre mostrar busque buscar busca encontre encontrar "
    "consulte consultar consulta sobre resuma resumir resumo analise analisar compara compare "
    "comparar negocio negocios oportunidade oportunidades salvo salvos salva salvas banco crm "
    "ares funil minha minhas meu meus todas todos esta estao tem tenho como qual e se situacao "
    "informacoes informacao detalhes detalhe favor porfavor ola oi bom dia boa tarde noite "
    "atual atualizadas atuais listar liste lista valor valores status etapa etapas proximo proximos "
    "passo passos dela dele dessa desse desse desta deste essas esses delas deles ela ele "
    "risco riscos atencao maior maiores menor menores prioridade prioridades abertas aberto abertos "
    "aberta fechadas fechados fechada fechado atrasado atrasados atrasada atrasadas "
    "algum alguns alguma algumas dado dados disponivel disponiveis existente existentes "
    "existem cadastrado cadastrados cadastrada cadastradas registrado registrados "
    "registrada registradas encontrado encontrados encontrada encontradas traga trazer "
    "forneca mostre mostra exiba ver veja disponiveis disponivel "
    "descreva descrever explique explicar diga fale falar apresente apresentar "
    "relacione relacionar panorama visao geral resumo sintetize sintetizar "
    "temos hoje agora nossa nossas nosso nossos sao ha atualmente nome nomes".split()
)
STOP_WORDS.update(
    "melhor melhores pior piores mais menos dessas desses dentre entre elas eles porque "
    "primeira primeiro segunda segundo terceira terceiro quanto custa vale motivo motivos "
    "urgente urgentes urgencia priorizar interessante interessantes devo deve devemos deveria".split()
)


def normalize(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )


def search_terms(text: str) -> list[str]:
    # An explicitly supplied name remains a name even when it contains a superlative.
    explicit = re.search(r'(?:nome|chamad[ao])\s+["“]?([^"”]+)', normalize(text))
    if explicit:
        return re.findall(r"[\w-]+", explicit.group(1))[:12]
    return list(
        dict.fromkeys(
            word
            for word in re.findall(r"[\w-]+", normalize(text))
            if len(word) > 1 and word not in STOP_WORDS
        )
    )[:12]


def comparison_criterion(question: str) -> str | None:
    words = re.split(r"\b(?:nome|chamad[ao])\b", normalize(question), maxsplit=1)[0]
    words = re.sub(r'["“][^"”]*["”]', "", words)
    if re.search(r"\b(estrategias?|treinamento|modelos?|probabilidade|chance|configurar)\b", words):
        return None
    if re.search(r"\b(priorizar|prioridades?|urgentes?|urgencia)\b", words):
        return "urgency"
    if re.search(r"\b(melhor|melhores|maior|maiores|menor|menores|mais|menos)\b", words):
        if re.search(r"\b(menor|menores|menos)\b", words) and "valor" in words:
            return "lowest_value"
        if re.search(r"\b(melhor|melhores)\b", words) or "valor" in words:
            return "value"
    return None


def numeric_value(item: dict[str, Any]) -> Decimal | None:
    try:
        value = Decimal(str(item.get("value")))
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def is_open(item: dict[str, Any]) -> bool:
    stage = normalize(str(item.get("external_stage") or item.get("canonical_stage") or ""))
    status = normalize(str(item.get("status") or ""))
    state = str(item.get("opportunity_state") or "")
    return (
        state not in {"resolved", "expired", "cancelled", "closed"}
        and stage not in {"won", "lost", "ganho", "perdido"}
        and status
        not in {
            "won",
            "lost",
            "closed",
            "ganho",
            "perdido",
            "fechado",
        }
    )


def make_context(
    payload: dict[str, Any] | None = None,
    *,
    source: str = "Conversa",
    citations: list[dict[str, Any]] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    content = json.dumps(payload or {}, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(content.encode()) > CONTEXT_LIMIT:
        raise ValueError("chat_context_too_large")
    return {
        "context_ref": str(uuid4()),
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "tokens_upper_bound": len(content.encode()),
        "token_limit": CONTEXT_LIMIT,
        "count_method": "utf8_bytes_upper_bound",
        "citations": citations or [],
        "truncated": truncated,
        "captured_at": datetime.now(UTC),
        "source": source,
    }


class OpportunitySearch:
    """Compatibility facade: the Context Builder owns all commercial reads."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def read(
        self, user: AuthenticatedUser, question: str, references: list[str] | None = None
    ) -> dict[str, Any]:
        from ares.intelligence.context_builder import ContextBuilder, ContextUnavailable
        from ares.intelligence.queries import intent_from_question

        try:
            builder = ContextBuilder(self.settings.database_url)
            intent = intent_from_question(question, references, timezone=builder.timezone(user))
            result = builder.build(user, intent, purpose="chat")
            if (
                intent.name
                and references is None
                and not re.search(r"\b(nome|chamad[ao])\b", normalize(question))
                and not result["result"].get("matches")
            ):
                # A free-form analytical sentence is not a business identifier.
                # Explicit names and historical references never expand their scope.
                result = builder.build(
                    user, intent.model_copy(update={"name": None}), purpose="chat"
                )
            return result
        except ContextUnavailable as error:
            from ares.chat.service import ChatFailure

            raise ChatFailure(error.code, error.status) from None
