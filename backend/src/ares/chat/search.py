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

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.connectors.http_fake_crm import CRMProviderRequestError
from ares.connectors.resolver import TenantCRMProvider

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
    def __init__(self, settings: Settings):
        self.settings = settings

    def read(
        self, user: AuthenticatedUser, question: str, references: list[str] | None = None
    ) -> dict[str, Any]:
        terms = references if references is not None else search_terms(question)
        criterion = comparison_criterion(question)
        if references == []:
            return make_context(
                {"matches": [], "limitations": ["Esse item não existe no recorte anterior."]}
            )
        ordering = {
            "value": "d.value desc nulls last,",
            "lowest_value": "d.value asc nulls last,",
            "urgency": "o.priority asc nulls last,o.score desc nulls last,",
        }.get(criterion or "", "")
        # Strip SQL wildcard semantics from the user terms. Values remain bound parameters.
        patterns = [f"%{word.replace('_', '')}%" for word in terms]
        stage_patterns = [
            f"%{word}%" for term in terms for word in STAGE_ALIASES.get(term, (term,))
        ]
        if references is not None:
            patterns, stage_patterns = [], []
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as db:
            db.execute("set local statement_timeout='5s'")
            connections = db.execute(
                "select id,provider,status from public.connections where tenant_id=%s",
                (user.tenant_id,),
            ).fetchall()
            # Match folded titles as well as database/CRM/ARES IDs. No customer/contact payloads.
            rows = db.execute(
                "select d.id,d.title,d.status,d.value,d.currency,d.canonical_stage,d.external_stage,"
                "d.source_changed_at,d.updated_at,coalesce(d.external_ref->>'id',d.external_id) external_id,"
                "d.external_id namespaced_id,d.connection_id,d.external_ref->>'provider' stored_provider,"
                "o.id opportunity_id,o.state opportunity_state,o.priority,o.score "
                "from public.deals d left join lateral (select id,state,priority,score "
                "from public.ares_opportunities where tenant_id=d.tenant_id and deal_id=d.id "
                "order by updated_at desc,id limit 1) o on true "
                "where d.tenant_id=%s and not d.is_missing "
                "and (d.connection_id is null or exists(select 1 from public.connections c "
                "where c.tenant_id=d.tenant_id and c.id=d.connection_id and c.status<>'revoked')) "
                "and (%s or translate(lower(d.title),"
                "'áàâãäéèêëíìîïóòôõöúùûüç','aaaaaeeeeiiiiooooouuuuc') like any(%s) "
                "or d.id::text=any(%s) or o.id::text=any(%s) "
                "or lower(coalesce(d.external_ref->>'id',d.external_id))=any(%s) "
                "or lower(d.external_id)=any(%s) "
                "or lower(coalesce(d.canonical_stage,'')) like any(%s) "
                "or lower(coalesce(d.external_stage,'')) like any(%s)) "
                "and (%s or (lower(coalesce(d.external_stage,d.canonical_stage,'')) "
                "not in ('won','lost','ganho','perdido') "
                "and lower(coalesce(d.status,'')) not in ('won','lost','closed','ganho','perdido','fechado'))) "
                "order by (select count(*) from unnest(%s::text[]) term "
                "where translate(lower(d.title),"
                "'áàâãäéèêëíìîïóòôõöúùûüç','aaaaaeeeeiiiiooooouuuuc') "
                "like '%%'||term||'%%') desc,"
                + ordering
                + "case when %s then coalesce(o.priority,0) else 0 end desc,"
                "d.updated_at desc,d.id limit 101",
                (
                    user.tenant_id,
                    not terms,
                    patterns,
                    terms,
                    terms,
                    terms,
                    terms,
                    stage_patterns,
                    stage_patterns,
                    criterion is None,
                    terms,
                    not terms,
                ),
            ).fetchall()
            # Opportunities without a linked CRM deal are still discoverable by their ARES ID.
            orphans = db.execute(
                "select id opportunity_id,state opportunity_state,priority,updated_at "
                "from public.ares_opportunities where tenant_id=%s and deal_id is null "
                "and (%s or id::text=any(%s)) order by updated_at desc,id limit 9",
                (user.tenant_id, not terms, terms),
            ).fetchall()

        def score(item: dict[str, Any]) -> int:
            title = normalize(str(item.get("title", "")))
            identifiers = {
                str(item.get(key, ""))
                for key in ("id", "external_id", "opportunity_id", "namespaced_id")
            }
            identifiers.update(str(ref) for ref in item.get("record_ids", []))
            if references is not None:
                return sum(10 for term in terms if term in identifiers)
            stage = normalize(
                f"{item.get('external_stage') or ''} {item.get('canonical_stage') or ''}"
            )
            return sum(
                10
                if term in identifiers
                else int(
                    term in title
                    or any(alias in stage for alias in STAGE_ALIASES.get(term, (term,)))
                )
                for term in terms
            )

        items = [{**dict(row), "source": "Banco ARES (espelho do CRM)"} for row in rows]
        items.extend({**dict(row), "source": "Oportunidade ARES"} for row in orphans)
        limitations: list[str] = []
        crm_read = False
        truncated = len(rows) > 100 or len(orphans) > RESULT_LIMIT
        connection = next((row for row in connections if row["provider"] == "fake-crm-http"), None)
        if connection and self.settings.environment == "development":
            # The local journal's original FakeCRM IDs predate connection namespacing.
            # Fold only that known development source into its configured HTTP sandbox.
            for item in items:
                if item.get("connection_id") is None and item.get("stored_provider") == "fake-crm":
                    item["connection_id"] = connection["id"]
        if connection and connection["status"] != "revoked":
            if self.settings.environment in {"development", "demonstration"}:
                provider = TenantCRMProvider(self.settings, user.tenant_id)
                provider.connection_id = connection["id"]
                try:
                    cursor = None
                    for _ in range(CRM_PAGE_LIMIT):
                        page = provider.list_deals(cursor=cursor, limit=100)
                        crm_read = True
                        for deal in page.items:
                            live: dict[str, Any] = {
                                "external_id": deal.id,
                                "connection_id": connection["id"],
                                "title": deal.title[:160],
                                "external_stage": deal.stage,
                                "value": deal.value,
                                "currency": deal.currency,
                                "source_changed_at": deal.changed_at,
                                "source": "CRM conectado · FakeCRM (dados sintéticos)",
                            }
                            mirrors = [
                                row
                                for row in items
                                if row.get("external_id") == deal.id
                                and row.get("connection_id") == connection["id"]
                            ]
                            if mirrors:
                                # Live CRM wins for funnel fields; keep ARES identity separate.
                                for mirror in mirrors:
                                    mirror.update(live)
                                    mirror.pop("status", None)
                                    mirror.pop("canonical_stage", None)
                            elif not terms or score(live):
                                items.append(live)
                        cursor = page.next_cursor
                        if cursor is None:
                            break
                    if cursor is not None:
                        truncated = True
                        limitations.append(
                            "CRM consultado até 500 negócios; há mais páginas não consultadas."
                        )
                except (CRMProviderRequestError, ValueError):
                    limitations.append(
                        "CRM indisponível nesta consulta; os dados salvos podem estar desatualizados."
                    )
            else:
                limitations.append("Adaptador do CRM não configurado para este ambiente/empresa.")
        else:
            if any(row["status"] != "revoked" for row in connections):
                limitations.append(
                    "Adaptador de leitura do CRM não configurado para esta conexão; "
                    "consulta limitada ao banco ARES."
                )
            else:
                limitations.append(
                    "Nenhuma conexão ativa com CRM disponível; consulta limitada ao banco ARES."
                )
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for item in items:
            key = (
                (str(item.get("connection_id")), str(item.get("external_id")))
                if item.get("external_id")
                else ("record", str(item.get("id") or item.get("opportunity_id")))
            )
            prior = groups.get(key)
            if prior is None:
                groups[key] = item
                continue
            native = str(item.get("namespaced_id", "")).startswith(
                str(item.get("connection_id")) + ":"
            )
            chosen = item if native else prior
            chosen["record_ids"] = list(
                dict.fromkeys(
                    str(ref)
                    for row in (prior, item)
                    for ref in [row.get("id"), *row.get("record_ids", [])]
                    if ref
                )
            )
            chosen["ares_opportunity_ids"] = list(
                dict.fromkeys(
                    str(ref)
                    for row in (prior, item)
                    for ref in [row.get("opportunity_id"), *row.get("ares_opportunity_ids", [])]
                    if ref
                )
            )
            priorities = [
                row["priority"] for row in (prior, item) if row.get("priority") is not None
            ]
            if priorities:
                chosen["priority"] = min(priorities)
            chosen["score"] = max(prior.get("score") or 0, item.get("score") or 0)
            groups[key] = chosen
        items = [item for item in groups.values() if not terms or score(item)]
        if criterion:
            items = [item for item in items if is_open(item)]
        if criterion in {"value", "lowest_value"}:
            # An ARES opportunity without a CRM deal is not a priced business.
            items = [item for item in items if item.get("id") or item.get("external_id")]
            items.sort(
                key=lambda item: (numeric_value(item) is None, numeric_value(item) or Decimal(0)),
                reverse=False,
            )
            if criterion == "value":
                items = [item for item in items if numeric_value(item) is not None][::-1] + [
                    item for item in items if numeric_value(item) is None
                ]
        elif criterion == "urgency":
            items.sort(
                key=lambda item: (
                    item.get("priority") if item.get("priority") is not None else 4,
                    -(item.get("score") or 0),
                )
            )
        else:
            items.sort(key=score, reverse=True)
        currencies = list(
            dict.fromkeys(item.get("currency") for item in items if numeric_value(item) is not None)
        )
        if criterion in {"value", "lowest_value"} and len(currencies) > 1:
            leaders = [
                next(
                    item
                    for item in items
                    if item.get("currency") == currency and numeric_value(item) is not None
                )
                for currency in currencies
            ]
            items = leaders + [item for item in items if item not in leaders]
        truncated = truncated or len(items) > RESULT_LIMIT
        items = items[:RESULT_LIMIT]
        for item in items:
            if "title" in item:
                item["title"] = str(item["title"])[:160]
        payload = {
            "search_query": question[:400],
            "matches": items,
            "limitations": limitations,
            "criterion": criterion,
            "currencies": currencies,
            "interpretation": "Resultados por nome ou identificador; não representam totais do funil. "
            "Negócio do CRM e Oportunidade ARES são entidades distintas. "
            "Peça confirmação quando houver mais de um resultado possível.",
        }
        if (
            criterion
            and items
            and (
                (criterion == "urgency" and items[0].get("priority") is not None)
                or (criterion != "urgency" and len(currencies) == 1 and None not in currencies)
            )
        ):
            selected = items[0]
            payload["selection"] = str(
                selected.get("id") or selected.get("external_id") or selected.get("opportunity_id")
            )
        while (
            len(json.dumps(payload, default=str, ensure_ascii=False).encode()) > CONTEXT_LIMIT - 300
        ):
            items.pop()
            truncated = True
        citations = [
            {
                "event_id": str(
                    item.get("opportunity_id") or item.get("external_id") or item.get("id")
                ),
                "event_type": "crm.deal.read"
                if "CRM conectado" in item["source"]
                else "database.deal.read",
                "occurred_at": str(item.get("source_changed_at") or item.get("updated_at") or ""),
                "source": item["source"],
                "source_ref": str(
                    item.get("external_id") or item.get("id") or item.get("opportunity_id")
                ),
                "opportunity_id": str(item["opportunity_id"])
                if item.get("opportunity_id")
                else None,
            }
            for item in items
        ]
        return make_context(
            payload,
            source="Banco ARES + CRM conectado" if crm_read else "Banco ARES",
            citations=citations,
            truncated=truncated,
        )
