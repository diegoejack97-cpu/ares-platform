"""Personal, idempotent finding conversations; historical evidence is never current fact."""
# SQL statements remain complete for audit review.
# ruff: noqa: E501

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.intelligence.context_builder import ContextBuilder, ContextUnavailable, fingerprint
from ares.intelligence.queries import QueryIntent
from ares.sentinels.findings import predicate, snapshot_expression
from ares.sentinels.notifications import scope_on
from ares.sentinels.service import SentinelScheduleConflict


def safe_text(value: Any) -> str:
    return str(value if value is not None else "Não informado").replace("\n", " ")[:160]


class FindingChat:
    def __init__(self, url: str):
        self.url = url

    def resolve(self, user: AuthenticatedUser, finding: UUID) -> dict[str, Any]:
        from ares.chat.service import ChatFailure

        try:
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                db.execute("set local statement_timeout='5s'")
                owner = scope_on(db, user)
                member = db.execute(
                    "select role::text role from public.memberships where tenant_id=%s and user_id=%s",
                    (user.tenant_id, user.user_id),
                ).fetchone()
                if not member or member["role"] not in {"admin", "manager", "seller"}:
                    raise ChatFailure("finding_chat_unavailable", 403)
                row = db.execute(
                    "select f.*,s.title rule_title,s.kind,s.threshold_hours,s.criteria_json,s.version,s.archived_at,s.enabled from public.sentinel_findings f join public.sentinel_schedules s on s.tenant_id=f.tenant_id and s.rule_id=f.rule_id join public.ares_opportunities o on o.tenant_id=f.tenant_id and o.id=f.opportunity_id where f.tenant_id=%s and f.id=%s and (%s::uuid is null or o.owner_user_id=%s)",
                    (user.tenant_id, finding, owner, owner),
                ).fetchone()
                if not row:
                    raise ChatFailure("finding_not_found", 404)
                where, params = predicate(row)
                current = db.execute(
                    f"select {snapshot_expression(row['kind'])} observed,({where}) still_matches from public.ares_opportunities o left join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id where o.tenant_id=%s and o.id=%s",
                    [row["threshold_hours"], *params, user.tenant_id, row["opportunity_id"]],
                ).fetchone()
                assert current
                previous = row["evidence"].get("observed", row["evidence"])
                observed = current["observed"]
                active = bool(
                    current["still_matches"] and row["enabled"] and not row["archived_at"]
                )
                changed = observed != previous or str(row["version"]) != row["rule_version"]
                return {
                    "finding_id": str(finding),
                    "opportunity_id": str(row["opportunity_id"]),
                    "revision": row["revision"],
                    "rule_title": safe_text(row["rule_title"]),
                    "rule_kind": row["kind"],
                    "rule_version": row["rule_version"],
                    "current_rule_version": row["version"],
                    "title": safe_text(observed.get("title")),
                    "detected_at": row["detected_at"].isoformat(),
                    "status": row["status"],
                    "condition_current": active,
                    "changed": changed,
                    "original": {
                        k: previous.get(k)
                        for k in (
                            "stage",
                            "value",
                            "currency",
                            "sla_at",
                            "state",
                            "priority",
                            "score",
                        )
                    },
                    "current": {
                        k: observed.get(k)
                        for k in (
                            "stage",
                            "value",
                            "currency",
                            "sla_at",
                            "state",
                            "priority",
                            "score",
                        )
                    },
                    "summary": safe_text(row["summary"]),
                    "source": "Sentinela / evidência persistida e leitura atual do ARES Core",
                    "suggestions": [
                        "Por que essa oportunidade exige atenção?",
                        "O que mudou desde o alerta?",
                        "O que faço agora?",
                    ],
                }
        except SentinelScheduleConflict:
            raise ChatFailure("finding_access_denied", 403) from None

    def open(self, user: AuthenticatedUser, finding: UUID) -> dict[str, Any]:
        from ares.chat.service import ChatFailure

        origin = self.resolve(user, finding)
        try:
            context = ContextBuilder(self.url).build(
                user,
                QueryIntent(entity="opportunity", scope_ref=UUID(origin["opportunity_id"])),
                purpose="chat",
            )
        except ContextUnavailable as error:
            raise ChatFailure(error.code, error.status) from None
        answer = finding_answer(origin)
        signature = fingerprint(
            [origin["current"], origin["condition_current"], origin["current_rule_version"]]
        )
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            owner = scope_on(db, user)
            row = db.execute(
                "select f.revision from public.sentinel_findings f join public.ares_opportunities o on o.tenant_id=f.tenant_id and o.id=f.opportunity_id where f.tenant_id=%s and f.id=%s and (%s::uuid is null or o.owner_user_id=%s) for share of f,o",
                (user.tenant_id, finding, owner, owner),
            ).fetchone()
            if not row:
                raise ChatFailure("finding_not_found", 404)
            if row["revision"] != origin["revision"]:
                raise ChatFailure("finding_changed", 409)
            # Serialize both double-clicks and multiple tabs on the personal thread.
            conversation = db.execute(
                "insert into public.conversations(tenant_id,owner_user_id,opportunity_id,finding_id) values(%s,%s,%s,%s) on conflict(tenant_id,owner_user_id,finding_id) where finding_id is not null do update set owner_user_id=excluded.owner_user_id returning id",
                (user.tenant_id, user.user_id, origin["opportunity_id"], finding),
            ).fetchone()
            assert conversation
            prior = db.execute(
                "select message_id from public.sentinel_chat_openings where tenant_id=%s and finding_id=%s and user_id=%s and revision=%s and context_hash=%s",
                (user.tenant_id, finding, user.user_id, origin["revision"], signature),
            ).fetchone()
            if not prior:
                # Reject a concurrent commercial update before storing an explanation.
                ContextBuilder(self.url).read(user, UUID(context["context_ref"]))
                run, message = uuid4(), uuid4()
                context["finding_origin"] = origin
                db.execute(
                    "insert into public.agent_runs(id,tenant_id,opportunity_id,context_ref,correlation_id,agent_name,agent_version,prompt_hash,output_schema_version,generation_mode,status,finished_at) values(%s,%s,%s,%s,%s,'chat','finding-opening.v1',%s,'chat.v3','deterministic_fallback','succeeded',now())",
                    (
                        run,
                        user.tenant_id,
                        origin["opportunity_id"],
                        context["context_ref"],
                        uuid4(),
                        hashlib.sha256(answer.encode()).hexdigest(),
                    ),
                )
                db.execute(
                    "insert into public.messages(id,tenant_id,conversation_id,run_id,user_text,assistant_text,status,context_json,tool_calls_json) values(%s,%s,%s,%s,'Explique esta notificação.',%s,'succeeded',%s,%s)",
                    (
                        message,
                        user.tenant_id,
                        conversation["id"],
                        run,
                        answer,
                        Jsonb(json.loads(json.dumps(context, default=str))),
                        Jsonb([{"name": "sentinel_handoff", "status": "completed"}]),
                    ),
                )
                db.execute(
                    "insert into public.sentinel_chat_openings(tenant_id,finding_id,user_id,revision,context_hash,message_id) values(%s,%s,%s,%s,%s,%s)",
                    (user.tenant_id, finding, user.user_id, origin["revision"], signature, message),
                )
            db.execute(
                "insert into public.sentinel_notification_state(tenant_id,finding_id,user_id,read_revision) values(%s,%s,%s,%s) on conflict(tenant_id,finding_id,user_id) do update set read_revision=excluded.read_revision,updated_at=now()",
                (user.tenant_id, finding, user.user_id, origin["revision"]),
            )
        return {
            "finding": origin,
            "conversation_id": str(conversation["id"]),
            "reused": bool(prior),
        }

    def feedback(
        self, user: AuthenticatedUser, message: UUID, rating: str, reason: str
    ) -> dict[str, Any]:
        from ares.chat.service import ChatFailure, ChatService

        with psycopg.connect(self.url, row_factory=dict_row) as db:
            scope_on(db, user)
            row = db.execute(
                "select m.run_id,m.context_json,c.finding_id,c.opportunity_id from public.messages m join public.conversations c on c.tenant_id=m.tenant_id and c.id=m.conversation_id where m.tenant_id=%s and m.id=%s and c.owner_user_id=%s and m.status='succeeded'",
                (user.tenant_id, message, user.user_id),
            ).fetchone()
            if not row:
                raise ChatFailure("message_not_found", 404)
            if row["finding_id"]:
                self.resolve(user, row["finding_id"])
            else:
                from ares.config import Settings

                service = ChatService(Settings(database_url=self.url))
                if row["opportunity_id"]:
                    service.context(user, row["opportunity_id"])
                else:
                    service.authorize(user)
            db.execute(
                "insert into public.chat_feedback(tenant_id,message_id,user_id,rating,reason,run_id,context_ref) values(%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id,message_id,user_id) do update set rating=excluded.rating,reason=excluded.reason,updated_at=now()",
                (
                    user.tenant_id,
                    message,
                    user.user_id,
                    rating,
                    reason,
                    row["run_id"],
                    row["context_json"]["context_ref"],
                ),
            )
        return {"message_id": str(message), "rating": rating}


def display_money(value: Any, currency: Any) -> str:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return "Não informado"
        formatted = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{safe_text(currency)} {formatted}"
    except (ValueError, InvalidOperation):
        return "Não informado"


def finding_answer(origin: dict[str, Any], question: str = "") -> str:
    from ares.chat.search import normalize

    words = normalize(question)
    current = origin["current"]
    situation = (
        "A condição da regra continua presente na leitura atual."
        if origin["condition_current"]
        else "A condição original não está mais ativa nesta leitura. O alerta é histórico; não recomenda uma ação atual por si só."
    )
    change = (
        "Os dados ou a configuração mudaram desde a detecção."
        if origin["changed"]
        else "Não identifiquei mudança nos campos observados desde a detecção."
    )
    reason = {
        "sla_overdue": "O prazo de SLA observado ultrapassou o limite configurado.",
        "unassigned": "A oportunidade ficou sem responsável pelo período configurado.",
        "stale": "A oportunidade não recebeu atualização dentro do período configurado.",
    }[origin["rule_kind"]]
    stage = {
        "new": "Entrada",
        "qualification": "Qualificação",
        "proposal": "Proposta",
        "negotiation": "Negociação",
        "won": "Ganho",
        "lost": "Perdido",
    }.get(str(current.get("stage")), safe_text(current.get("stage")))
    state = {
        "detected": "Detectada",
        "prioritized": "Priorizada",
        "awaiting_decision": "Aguardando decisão",
        "executing": "Em execução",
        "closed": "Encerrada",
    }.get(str(current.get("state")), safe_text(current.get("state")))
    answer = f"**{origin['title']}**\n\n{origin['summary']} {reason}\n\n{situation}\n\n{change}"
    if "mud" in words:
        labels = {
            "stage": "Etapa",
            "value": "Valor",
            "currency": "Moeda",
            "sla_at": "SLA",
            "state": "Estado",
            "priority": "Prioridade Core",
            "score": "Score Core",
        }
        changes = [
            f"- {label}: {safe_text(origin['original'].get(key))} → {safe_text(current.get(key))}"
            for key, label in labels.items()
            if origin["original"].get(key) != current.get(key)
        ]
        answer += "\n\n" + (
            "\n".join(changes)
            if changes
            else "Os campos observados permanecem iguais; uma alteração da regra pode explicar a revisão."
        )
    else:
        answer += f"\n\n**Dados atuais:** etapa {stage}; valor {display_money(current.get('value'), current.get('currency'))}; estado {state}."
    if "valor" in words or "quant" in words:
        answer += "\n\nEste contexto é de uma oportunidade, não representa o total da carteira."
    answer += "\n\n**Próximo passo:** confira o responsável, o prazo e o último contato no detalhe da oportunidade antes de preparar uma intervenção. O chat não aprova nem executa ações no CRM."
    answer += "\n\nFonte: achado persistido da sentinela e leitura atual do ARES Core. Sem estimativa de probabilidade ou receita incremental."
    return answer
