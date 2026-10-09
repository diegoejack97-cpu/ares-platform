# SQL strings remain complete for review.
# ruff: noqa: E501
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.impact.service import ImpactService


class CommandCenterDenied(Exception):
    pass


MAIN_PATH_STATES = (
    "detected",
    "prioritized",
    "awaiting_decision",
    "authorized",
    "executing",
    "observing",
    "closed",
)
STATE_LABELS = {
    "detected": "Detectadas",
    "prioritized": "Priorizadas",
    "awaiting_decision": "Aguardando decisão",
    "authorized": "Autorizadas",
    "executing": "Em execução",
    "observing": "Em observação",
    "closed": "Encerradas",
}
SNAPSHOT_PERIOD = "Retrato na data da consulta"
SOURCE = (
    "Supabase/PostgreSQL — oportunidades, sinais, transições, aprovações, "
    "execuções, conexões e outcomes"
)
QUEUE_LIMIT = 8
ITEMS_LIMIT = 5
ACTIVITY_LIMIT = 25
SELLER_AI_COST_NOTE = (
    "Custo de IA é medido por tenant, não por vendedor; indisponível no escopo próprio."
)
DAY_EDGE_NOTE = (
    " O primeiro dia da janela pode estar incompleto porque o período começa no mesmo "
    "horário de hoje, N dias atrás; dias sem registros são zeros reais."
)

# Seller scope: only opportunities they own. `o` is always public.ares_opportunities.
SCOPE = " and (%(owner)s::uuid is null or o.owner_user_id = %(owner)s)"
OBSERVATION = "Observação operacional"


def window_period(days: int) -> str:
    return f"Janela de {days} dias, início inclusivo e fim exclusivo, UTC"


def pad_funnel(reached: dict[str, int]) -> list[dict[str, Any]]:
    """Every main-path state, in machine order, never sorted by count."""
    return [
        {"state": state, "label": STATE_LABELS[state], "reached": int(reached.get(state, 0))}
        for state in MAIN_PATH_STATES
    ]


def _definition(
    key: str,
    label: str,
    formula: str,
    tables: list[str],
    period: str,
    attribution_level: str | None = None,
    attribution: str = OBSERVATION,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "formula": formula,
        "tables": tables,
        "period": period,
        "attribution_level": attribution_level,
        "attribution": attribution,
    }


def definitions(days: int) -> list[dict[str, Any]]:
    """Formulas travel with the data; the UI never authors one."""
    window = window_period(days)
    snapshot = SNAPSHOT_PERIOD
    opp = ["ares_opportunities"]
    return [
        _definition(
            "open_at_risk",
            "Abertas em risco",
            "Oportunidades com estado diferente de closed na data da consulta; retrato do agora, não uma reconstrução histórica.",
            opp,
            snapshot,
        ),
        _definition(
            "critical",
            "Críticas",
            "Oportunidades abertas com prioridade 0 (SLA de 4 h), a maior urgência do motor de score. Não é previsão de fechamento.",
            opp,
            snapshot,
        ),
        _definition(
            "sla_overdue",
            "SLA vencido",
            "Abertas com sla_at anterior ao momento da consulta.",
            opp,
            snapshot,
        ),
        _definition(
            "sla_next_6h",
            "Próximas 6 h",
            "Abertas com sla_at entre a consulta e a consulta + 6 h (limiar crítico do SlaCountdown).",
            opp,
            snapshot,
        ),
        _definition(
            "sla_missing",
            "Sem prazo",
            "Abertas sem sla_at; ficam fora dos contadores de SLA.",
            opp,
            snapshot,
        ),
        _definition(
            "without_owner",
            "Sem responsável",
            "Abertas com owner_user_id nulo; um vendedor nunca as vê no escopo próprio.",
            opp,
            snapshot,
        ),
        _definition(
            "awaiting_decision",
            "Aguardando decisão",
            "Abertas no estado awaiting_decision (recomendação gerada, decisão humana pendente).",
            opp,
            snapshot,
        ),
        _definition(
            "value_at_risk",
            "Valor em risco",
            "Soma de deals.value das oportunidades abertas em risco, separada por moeda; negócios sem valor ou sem moeda ficam fora do total e são contados como 'sem valor'/'sem moeda'. Moedas nunca são somadas entre si.",
            ["ares_opportunities", "deals"],
            snapshot,
        ),
        _definition(
            "queue",
            "Fila prioritária",
            "As 8 oportunidades abertas na mesma ordenação canônica do Radar (prioridade, prazo mais próximo, score); a fila completa está no Radar. Sem recomendação inventada pelo frontend.",
            ["ares_opportunities", "deals", "approval_requests"],
            snapshot,
        ),
        _definition(
            "approvals",
            "Aprovações pendentes",
            "approval_requests com status pending na data da consulta, na mesma ordem da tela Aprovações (prioridade, expiração, criação). 'Expirando' = expires_at ainda futuro e dentro de 6 h; as já expiradas continuam listadas. Não é limitada ao período: uma aprovação antiga continua exigindo uma pessoa.",
            ["approval_requests", "recommendations", "ares_opportunities"],
            snapshot,
        ),
        _definition(
            "failed_actions",
            "Ações falhas",
            "Execuções no CRM com status failed no período (action_executions), com tentativas contadas pelo worker e correlation_id para investigação. Zero significa nenhuma falha registrada, não sucesso comprovado. Localmente o FakeCRM nunca falha; a lista vazia é real.",
            ["action_executions", "ares_interventions"],
            window,
        ),
        _definition(
            "connections",
            "Integrações degradadas",
            "Conexões com status degraded ou revoked em public.connections; configured e healthy não contam. A correção acontece no Laboratório CRM (apenas em desenvolvimento) ou no provedor.",
            ["connections"],
            snapshot,
        ),
        _definition(
            "trend_opened",
            "Abertas por dia",
            "Oportunidades por opened_at (data UTC)." + DAY_EDGE_NOTE,
            opp,
            window,
        ),
        _definition(
            "trend_worked",
            "Trabalhadas por dia",
            "Intervenções criadas (ares_interventions.created_at)." + DAY_EDGE_NOTE,
            ["ares_interventions"],
            window,
        ),
        _definition(
            "trend_executed",
            "Executadas por dia",
            "Ações no CRM concluídas com sucesso (action_executions.finished_at)." + DAY_EDGE_NOTE,
            ["action_executions"],
            window,
        ),
        _definition(
            "trend_failed",
            "Falhas por dia",
            "Execuções com status failed." + DAY_EDGE_NOTE,
            ["action_executions"],
            window,
        ),
        _definition(
            "funnel",
            "Funil de intervenção",
            "Coorte de oportunidades abertas no período; cada etapa conta quantas dessas registraram transição para aquele estado até a consulta. Etapas seguem o caminho principal da máquina de estados; como qualquer estado pode ir direto para closed, 'Encerradas' pode superar 'Em observação'. qualifying e qualified existem na máquina mas o motor atual não os usa. Não é o funil de etapas do CRM (ver Radar › Exposição por etapa).",
            ["ares_opportunities", "opportunity_state_transitions"],
            window,
        ),
        _definition(
            "signals",
            "Sinais por tipo",
            "Sinais detectados por dia (signals.detected_at, horário de processamento do ARES, UTC) e por signal_type, no período. severity é fixa por regra (3 a 5 hoje). Um mesmo negócio pode gerar vários sinais. Sinais sem oportunidade contam em cobertura e ficam fora do escopo próprio.",
            ["signals"],
            window,
        ),
        _definition(
            "heatmap",
            "Quando os sinais são detectados",
            "Dia da semana × faixa de 6 h do horário em que o ARES registrou o sinal (detected_at, UTC), não do evento no CRM. Mostra concentração de processamento, não comportamento do cliente.",
            ["signals"],
            window,
        ),
        _definition(
            "activity",
            "Atividade",
            "Os 25 eventos mais recentes do período entre mudanças de estado relevantes (detectada, aguardando decisão, autorizada, em observação, encerrada), decisões, execuções de ação e outcomes observados. Cada linha traz o correlation_id da cadeia; outcomes trazem o nível de atribuição. Não inclui audit_log de licenças e leads; o Event Journal guarda a trilha completa.",
            ["opportunity_state_transitions", "decisions", "action_executions", "outcomes"],
            window,
        ),
        _definition(
            "impact_at_risk",
            "Em risco identificadas",
            "Oportunidades abertas na data da consulta; não é uma reconstrução histórica.",
            opp,
            snapshot,
            "observed",
            "Observado",
        ),
        _definition(
            "impact_worked",
            "Trabalhadas",
            "Oportunidades com intervenção aberta no período.",
            ["ares_opportunities", "ares_interventions"],
            window,
            "observed",
            "Observado",
        ),
        _definition(
            "impact_recovered",
            "Recuperadas",
            "Último outcome observado por oportunidade no período com result_type=recovered.",
            ["outcomes"],
            window,
            "observed",
            "Observado (result_type = recovered)",
        ),
        _definition(
            "impact_sales_observed",
            "Vendas após intervenção",
            "Último outcome observado por oportunidade no período com sale_value informado.",
            ["outcomes"],
            window,
            "observed",
            "Observado; sequência temporal, não causalidade",
        ),
        _definition(
            "impact_sale_value",
            "Valor vendido",
            "Soma de sale_value do último outcome por oportunidade no período, separada por moeda.",
            ["outcomes"],
            window,
            "observed",
            "Observado",
        ),
        _definition(
            "impact_ares_influenced_value",
            "Valor influenciado",
            "Soma de ares_influenced_value quando attribution_level é influenced ou incremental_proven. Valor influenciado não prova causalidade.",
            ["outcomes"],
            window,
            "influenced",
            "Influenciado — não prova causalidade",
        ),
        _definition(
            "impact_incremental_value",
            "Incremental comprovado",
            "Soma de incremental_value somente quando attribution_level é incremental_proven e há método registrado; senão permanece não comprovado.",
            ["outcomes"],
            window,
            "incremental_proven",
            "Incremental comprovado somente com método registrado; senão 'Não comprovado'",
        ),
        _definition(
            "impact_ai_cost",
            "Custo de IA",
            "Custo de IA em USD: apenas uso medido; cobertura parcial quando há execuções sem custo observado.",
            ["agent_runs", "model_usage"],
            window,
            None,
            "Medição de uso; cobertura parcial explícita",
        ),
    ]


RENDERED_KEYS = frozenset(item["key"] for item in definitions(30))
FORBIDDEN_CLAIMS = ("causou", "gerou receita", "causal ", "causalidade comprovada")


def _max_time(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


class CommandCenterService:
    def __init__(self, database_url: str, impact: ImpactService, environment: str):
        self.database_url = database_url
        self.impact = impact
        self.environment = environment

    @contextmanager
    def db(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute("set transaction isolation level repeatable read, read only")
            connection.execute("set local statement_timeout='10s'")
            yield connection

    def authorize(self, db: psycopg.Connection[Any], user: AuthenticatedUser) -> str:
        row = db.execute(
            "select m.role::text as role from public.memberships m "
            "join public.tenants t on t.id = m.tenant_id and t.status = 'active' "
            "join public.tenant_entitlements e on e.tenant_id = m.tenant_id "
            "where m.tenant_id = %(tenant)s and m.user_id = %(user)s and m.active "
            "and e.module = 'ares_connect' and e.status = 'active' and (e.expires_at is null or e.expires_at > now()) "
            "limit 1",
            {"tenant": user.tenant_id, "user": user.user_id},
        ).fetchone()
        if not row:
            raise CommandCenterDenied
        return str(row["role"])

    def summary(self, user: AuthenticatedUser, days: int = 30) -> dict[str, Any]:
        if not 1 <= days <= 365:
            raise ValueError("invalid_window")
        until = datetime.now(UTC)
        since = until - timedelta(days=days)
        with self.db() as db:
            role = self.authorize(db, user)
            owner = user.user_id if role == "seller" else None
            params = {"tenant": user.tenant_id, "since": since, "until": until, "owner": owner}
            now = self._now(db, params)
            impact = self.impact.snapshot(db, user.tenant_id, since, until, owner)
            if owner is not None:
                impact["ai_cost"] = None
                impact["definitions"] = [*impact["definitions"], SELLER_AI_COST_NOTE]
            trends = self._trends(db, params)
            signals = self._signals(db, params)
            coverage = self._coverage(db, params, signals, impact)
            return {
                "window": {"since": since, "until": until, "days": days},
                "scope": {
                    "mode": "own" if owner else "tenant",
                    "role": role,
                    "owner_user_id": owner,
                },
                "capabilities": {
                    "approve": role in ("admin", "manager"),
                    "assign": False,
                    "fix_connection": self.environment == "development",
                },
                "now": now,
                "impact": impact,
                "trends": trends,
                "funnel": self._funnel(db, params),
                "signals": signals,
                "heatmap": self._heatmap(db, params),
                "activity": self._activity(db, params),
                "coverage": coverage,
                "definitions": definitions(days),
                "source": SOURCE,
                "freshness_at": self._freshness(db, params),
                "computed_at": until,
            }

    # ------------------------------------------------------------------ now
    def _now(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> dict[str, Any]:
        counts = db.execute(
            "select count(*) open_at_risk, "
            "count(*) filter (where o.priority = 0) critical, "
            "count(*) filter (where o.sla_at is not null and o.sla_at <= %(until)s) sla_overdue, "
            "count(*) filter (where o.sla_at > %(until)s and o.sla_at <= %(until)s + interval '6 hours') sla_next_6h, "
            "count(*) filter (where o.sla_at is null) sla_missing, "
            "count(*) filter (where o.owner_user_id is null) without_owner, "
            "count(*) filter (where o.state = 'awaiting_decision') awaiting_decision, "
            "max(o.updated_at) freshness_at "
            "from public.ares_opportunities o "
            "where o.tenant_id = %(tenant)s and o.state <> 'closed'" + SCOPE,
            params,
        ).fetchone()
        assert counts
        value_at_risk = db.execute(
            "select d.currency, count(*) count, "
            "sum(d.value) filter (where d.value is not null) total, "
            "count(*) filter (where d.value is null) missing "
            "from public.ares_opportunities o "
            "left join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id "
            "where o.tenant_id = %(tenant)s and o.state <> 'closed'" + SCOPE + " "
            "group by d.currency order by d.currency nulls last",
            params,
        ).fetchall()
        queue = db.execute(
            "select o.id opportunity_id, d.title, o.state::text state, o.priority, o.score, o.sla_at, o.owner_user_id, "
            "o.primary_signal_type, o.signal_count, d.value deal_value, d.currency, a.id pending_approval_id "
            "from public.ares_opportunities o "
            "left join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id "
            "left join lateral (select a.id from public.approval_requests a "
            "                   where a.tenant_id = o.tenant_id and a.opportunity_id = o.id and a.status = 'pending' "
            "                   order by a.created_at limit 1) a on true "
            "where o.tenant_id = %(tenant)s and o.state <> 'closed'" + SCOPE + " "
            "order by o.priority, o.sla_at asc nulls last, o.score desc, o.id "
            "limit %(queue_limit)s",
            {**params, "queue_limit": QUEUE_LIMIT},
        ).fetchall()
        approvals = db.execute(
            "select count(*) over () pending, "
            "count(*) filter (where a.expires_at > %(until)s and a.expires_at <= %(until)s + interval '6 hours') over () expiring_within_6h, "
            "a.id approval_id, a.opportunity_id, d.title, r.urgency::text urgency, a.required_role::text required_role, a.expires_at, a.created_at, a.updated_at "
            "from public.approval_requests a "
            "join public.recommendations r on r.tenant_id = a.tenant_id and r.id = a.recommendation_id "
            "join public.ares_opportunities o on o.tenant_id = a.tenant_id and o.id = a.opportunity_id "
            "left join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id "
            "where a.tenant_id = %(tenant)s and a.status = 'pending'" + SCOPE + " "
            "order by o.priority, a.expires_at, a.created_at "
            "limit %(items_limit)s",
            {**params, "items_limit": ITEMS_LIMIT},
        ).fetchall()
        failed = db.execute(
            "select count(*) over () count, x.id execution_id, i.opportunity_id, d.title, "
            "x.executed_action->>'action_kind' action_kind, x.attempts, x.finished_at, x.correlation_id "
            "from public.action_executions x "
            "join public.ares_interventions i on i.tenant_id = x.tenant_id and i.id = x.intervention_id "
            "join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id "
            "left join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id "
            "where x.tenant_id = %(tenant)s and x.status = 'failed' "
            "and coalesce(x.finished_at, x.created_at) >= %(since)s and coalesce(x.finished_at, x.created_at) < %(until)s"
            + SCOPE
            + " "
            "order by coalesce(x.finished_at, x.created_at) desc "
            "limit %(items_limit)s",
            {**params, "items_limit": ITEMS_LIMIT},
        ).fetchall()
        connection_counts = db.execute(
            "select count(*) total, count(*) filter (where status = 'degraded') degraded, "
            "count(*) filter (where status = 'revoked') revoked, max(updated_at) freshness_at "
            "from public.connections where tenant_id = %(tenant)s",
            params,
        ).fetchone()
        assert connection_counts
        connection_items = db.execute(
            "select id connection_id, provider, status, last_sync_at from public.connections "
            "where tenant_id = %(tenant)s and status in ('degraded','revoked') order by updated_at desc",
            params,
        ).fetchall()
        approvals_freshness = max((row["updated_at"] for row in approvals), default=None)
        return {
            "open_at_risk": counts["open_at_risk"],
            "critical": counts["critical"],
            "sla_overdue": counts["sla_overdue"],
            "sla_next_6h": counts["sla_next_6h"],
            "sla_missing": counts["sla_missing"],
            "without_owner": counts["without_owner"],
            "awaiting_decision": counts["awaiting_decision"],
            "value_at_risk": [dict(row) for row in value_at_risk],
            "queue": [dict(row) for row in queue],
            "queue_limit": QUEUE_LIMIT,
            "approvals": {
                "pending": approvals[0]["pending"] if approvals else 0,
                "expiring_within_6h": approvals[0]["expiring_within_6h"] if approvals else 0,
                "items_limit": ITEMS_LIMIT,
                "items": [
                    {
                        key: row[key]
                        for key in (
                            "approval_id",
                            "opportunity_id",
                            "title",
                            "urgency",
                            "required_role",
                            "expires_at",
                            "created_at",
                        )
                    }
                    for row in approvals
                ],
            },
            "failed_actions": {
                "count": failed[0]["count"] if failed else 0,
                "items_limit": ITEMS_LIMIT,
                "items": [
                    {
                        key: row[key]
                        for key in (
                            "execution_id",
                            "opportunity_id",
                            "title",
                            "action_kind",
                            "attempts",
                            "finished_at",
                            "correlation_id",
                        )
                    }
                    for row in failed
                ],
            },
            "connections": {
                "total": connection_counts["total"],
                "degraded": connection_counts["degraded"],
                "revoked": connection_counts["revoked"],
                "items": [dict(row) for row in connection_items],
            },
            "freshness_at": _max_time(
                counts["freshness_at"], approvals_freshness, connection_counts["freshness_at"]
            ),
        }

    # --------------------------------------------------------------- trends
    def _trends(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> dict[str, Any]:
        rows = db.execute(
            "with grid as (select generate_series(%(since)s::date, %(until)s::date, interval '1 day')::date as day), "
            "opened as (select o.opened_at::date as day, count(*) n from public.ares_opportunities o "
            "           where o.tenant_id = %(tenant)s and o.opened_at >= %(since)s and o.opened_at < %(until)s"
            + SCOPE
            + " group by 1), "
            "worked as (select i.created_at::date as day, count(*) n from public.ares_interventions i "
            "           join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id "
            "           where i.tenant_id = %(tenant)s and i.created_at >= %(since)s and i.created_at < %(until)s"
            + SCOPE
            + " group by 1), "
            "executed as (select x.finished_at::date as day, count(*) n from public.action_executions x "
            "             join public.ares_interventions i on i.tenant_id = x.tenant_id and i.id = x.intervention_id "
            "             join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id "
            "             where x.tenant_id = %(tenant)s and x.status = 'succeeded' and x.finished_at >= %(since)s and x.finished_at < %(until)s"
            + SCOPE
            + " group by 1), "
            "failed as (select coalesce(x.finished_at, x.created_at)::date as day, count(*) n from public.action_executions x "
            "           join public.ares_interventions i on i.tenant_id = x.tenant_id and i.id = x.intervention_id "
            "           join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id "
            "           where x.tenant_id = %(tenant)s and x.status = 'failed' and coalesce(x.finished_at, x.created_at) >= %(since)s and coalesce(x.finished_at, x.created_at) < %(until)s"
            + SCOPE
            + " group by 1) "
            "select g.day, coalesce(op.n,0) opened, coalesce(w.n,0) worked, coalesce(e.n,0) executed, coalesce(f.n,0) failed "
            "from grid g left join opened op using (day) left join worked w using (day) left join executed e using (day) left join failed f using (day) "
            "order by g.day",
            params,
        ).fetchall()
        freshness = db.execute(
            "select greatest("
            "(select max(o.opened_at) from public.ares_opportunities o where o.tenant_id = %(tenant)s and o.opened_at >= %(since)s and o.opened_at < %(until)s"
            + SCOPE
            + "), "
            "(select max(i.created_at) from public.ares_interventions i join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id where i.tenant_id = %(tenant)s and i.created_at >= %(since)s and i.created_at < %(until)s"
            + SCOPE
            + "), "
            "(select max(x.finished_at) from public.action_executions x join public.ares_interventions i on i.tenant_id = x.tenant_id and i.id = x.intervention_id join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id where x.tenant_id = %(tenant)s and x.finished_at >= %(since)s and x.finished_at < %(until)s"
            + SCOPE
            + ")"
            ") freshness_at",
            params,
        ).fetchone()
        series = [
            ("opened", "Abertas"),
            ("worked", "Trabalhadas"),
            ("executed", "Executadas"),
            ("failed", "Falhas"),
        ]
        return {
            "days": [row["day"] for row in rows],
            "series": [
                {"key": key, "label": label, "values": [int(row[key]) for row in rows]}
                for key, label in series
            ],
            "freshness_at": freshness["freshness_at"] if freshness else None,
        }

    # --------------------------------------------------------------- funnel
    def _funnel(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> dict[str, Any]:
        rows = db.execute(
            "with cohort as (select o.id from public.ares_opportunities o "
            "                where o.tenant_id = %(tenant)s and o.opened_at >= %(since)s and o.opened_at < %(until)s"
            + SCOPE
            + ") "
            "select s.state, s.ord, count(distinct c.id) reached, (select count(*) from cohort) cohort "
            "from unnest(array['detected','prioritized','awaiting_decision','authorized','executing','observing','closed']) with ordinality s(state, ord) "
            "left join public.opportunity_state_transitions t on t.tenant_id = %(tenant)s and t.to_state::text = s.state and t.occurred_at < %(until)s "
            "left join cohort c on c.id = t.opportunity_id "
            "group by s.state, s.ord order by s.ord",
            params,
        ).fetchall()
        cohort = int(rows[0]["cohort"]) if rows else 0
        return {
            "cohort": cohort,
            "stages": pad_funnel({row["state"]: int(row["reached"]) for row in rows}),
        }

    # -------------------------------------------------------------- signals
    def _signals(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> dict[str, Any]:
        cells = db.execute(
            "select s.detected_at::date as day, s.signal_type, max(s.severity) severity, count(*) n "
            "from public.signals s "
            "left join public.ares_opportunities o on o.tenant_id = s.tenant_id and o.id = s.opportunity_id "
            "where s.tenant_id = %(tenant)s and s.detected_at >= %(since)s and s.detected_at < %(until)s"
            + SCOPE
            + " "
            "group by 1, 2 order by 1, 2",
            params,
        ).fetchall()
        coverage = db.execute(
            "select count(*) filter (where opportunity_id is null) without_opportunity, "
            "count(*) filter (where opportunity_id is not null) with_opportunity, max(detected_at) freshness_at "
            "from public.signals where tenant_id = %(tenant)s and detected_at >= %(since)s and detected_at < %(until)s",
            params,
        ).fetchone()
        assert coverage
        days = [
            row["day"]
            for row in db.execute(
                "select generate_series(%(since)s::date, %(until)s::date, interval '1 day')::date as day",
                params,
            ).fetchall()
        ]
        totals: dict[str, dict[str, int]] = {}
        for row in cells:
            entry = totals.setdefault(row["signal_type"], {"severity": 0, "total": 0})
            entry["severity"] = max(entry["severity"], int(row["severity"]))
            entry["total"] += int(row["n"])
        ordered = sorted(
            totals.items(), key=lambda item: (-item[1]["severity"], -item[1]["total"], item[0])
        )
        types = [
            {"signal_type": key, "severity": value["severity"], "total": value["total"]}
            for key, value in ordered
        ]
        return {
            "total": sum(int(row["n"]) for row in cells),
            "without_opportunity": int(coverage["without_opportunity"]),
            "with_opportunity": int(coverage["with_opportunity"]),
            "days": days,
            "types": types,
            "cells": [
                {"day": row["day"], "signal_type": row["signal_type"], "count": int(row["n"])}
                for row in cells
            ],
            "freshness_at": coverage["freshness_at"],
        }

    # -------------------------------------------------------------- heatmap
    def _heatmap(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> dict[str, Any]:
        rows = db.execute(
            "with grid as (select w weekday, b band from generate_series(0,6) w cross join generate_series(0,3) b), "
            "hits as (select extract(dow from s.detected_at)::int weekday, (extract(hour from s.detected_at)::int / 6) band, count(*) n "
            "         from public.signals s left join public.ares_opportunities o on o.tenant_id = s.tenant_id and o.id = s.opportunity_id "
            "         where s.tenant_id = %(tenant)s and s.detected_at >= %(since)s and s.detected_at < %(until)s"
            + SCOPE
            + " "
            "         group by 1, 2) "
            "select g.weekday, g.band, coalesce(h.n, 0) count from grid g left join hits h using (weekday, band) order by 1, 2",
            params,
        ).fetchall()
        return {
            "total": sum(int(row["count"]) for row in rows),
            "timezone": "UTC",
            "cells": [
                {
                    "weekday": int(row["weekday"]),
                    "band": int(row["band"]),
                    "count": int(row["count"]),
                }
                for row in rows
            ],
        }

    # ------------------------------------------------------------- activity
    def _activity(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> dict[str, Any]:
        rows = db.execute(
            "select ev.*, t.title from ( "
            "  select 'state' kind, t.occurred_at, t.actor_type::text actor_type, t.opportunity_id, t.to_state::text label, t.reason detail, null::text attribution_level, t.correlation_id "
            "    from public.opportunity_state_transitions t "
            "    join public.ares_opportunities o on o.tenant_id = t.tenant_id and o.id = t.opportunity_id "
            "    where t.tenant_id = %(tenant)s and t.to_state::text in ('detected','awaiting_decision','authorized','observing','closed') "
            "      and t.occurred_at >= %(since)s and t.occurred_at < %(until)s" + SCOPE + " "
            "  union all "
            "  select 'decision', dc.decided_at, dc.actor_type::text, i.opportunity_id, dc.verdict::text, dc.reason, null, dc.correlation_id "
            "    from public.decisions dc "
            "    join public.ares_interventions i on i.tenant_id = dc.tenant_id and i.id = dc.intervention_id "
            "    join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id "
            "    where dc.tenant_id = %(tenant)s and dc.decided_at >= %(since)s and dc.decided_at < %(until)s"
            + SCOPE
            + " "
            "  union all "
            "  select 'action', coalesce(x.finished_at, x.created_at), x.actor_type::text, i.opportunity_id, x.status::text, x.executed_action->>'action_kind', null, x.correlation_id "
            "    from public.action_executions x "
            "    join public.ares_interventions i on i.tenant_id = x.tenant_id and i.id = x.intervention_id "
            "    join public.ares_opportunities o on o.tenant_id = i.tenant_id and o.id = i.opportunity_id "
            "    where x.tenant_id = %(tenant)s and x.status::text in ('succeeded','failed') "
            "      and coalesce(x.finished_at, x.created_at) >= %(since)s and coalesce(x.finished_at, x.created_at) < %(until)s"
            + SCOPE
            + " "
            "  union all "
            "  select 'outcome', oc.observed_at, oc.actor_type::text, oc.opportunity_id, oc.result_type::text, oc.attribution_method, oc.attribution_level::text, oc.correlation_id "
            "    from public.outcomes oc "
            "    join public.ares_opportunities o on o.tenant_id = oc.tenant_id and o.id = oc.opportunity_id "
            "    where oc.tenant_id = %(tenant)s and oc.observed_at >= %(since)s and oc.observed_at < %(until)s"
            + SCOPE
            + " "
            ") ev "
            "left join lateral (select d.title from public.ares_opportunities o join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id "
            "                   where o.tenant_id = %(tenant)s and o.id = ev.opportunity_id) t on true "
            "order by ev.occurred_at desc limit %(fetch)s",
            {**params, "fetch": ACTIVITY_LIMIT + 1},
        ).fetchall()
        return {
            "limit": ACTIVITY_LIMIT,
            "truncated": len(rows) > ACTIVITY_LIMIT,
            "items": [dict(row) for row in rows[:ACTIVITY_LIMIT]],
        }

    # ------------------------------------------------------------- coverage
    def _coverage(
        self,
        db: psycopg.Connection[Any],
        params: dict[str, Any],
        signals: dict[str, Any],
        impact: dict[str, Any],
    ) -> dict[str, Any]:
        row = db.execute(
            "select count(*) opportunities, count(o.owner_user_id) opportunities_with_owner, "
            "count(o.sla_at) opportunities_with_sla, count(d.value) deals_with_value "
            "from public.ares_opportunities o left join public.deals d on d.tenant_id = o.tenant_id and d.id = o.deal_id "
            "where o.tenant_id = %(tenant)s and o.state <> 'closed'" + SCOPE,
            params,
        ).fetchone()
        assert row
        cost = impact.get("ai_cost")
        return {
            "opportunities": int(row["opportunities"]),
            "opportunities_with_owner": int(row["opportunities_with_owner"]),
            "opportunities_with_sla": int(row["opportunities_with_sla"]),
            "deals_with_value": int(row["deals_with_value"]),
            "signals_with_opportunity": int(signals["with_opportunity"]),
            "synthetic_outcomes": sum(
                int(amount["synthetic_observations"] or 0) for amount in impact["amounts"]
            ),
            "ai_runs": int(cost["runs"]) if cost else None,
            "ai_measured_runs": int(cost["measured_runs"]) if cost else None,
        }

    def _freshness(self, db: psycopg.Connection[Any], params: dict[str, Any]) -> datetime | None:
        row = db.execute(
            "select greatest("
            "(select max(o.updated_at) from public.ares_opportunities o where o.tenant_id = %(tenant)s"
            + SCOPE
            + "), "
            "(select max(s.detected_at) from public.signals s left join public.ares_opportunities o on o.tenant_id = s.tenant_id and o.id = s.opportunity_id where s.tenant_id = %(tenant)s"
            + SCOPE
            + "), "
            "(select max(t.occurred_at) from public.opportunity_state_transitions t join public.ares_opportunities o on o.tenant_id = t.tenant_id and o.id = t.opportunity_id where t.tenant_id = %(tenant)s"
            + SCOPE
            + "), "
            "(select max(x.observed_at) from public.outcomes x join public.ares_opportunities o on o.tenant_id = x.tenant_id and o.id = x.opportunity_id where x.tenant_id = %(tenant)s"
            + SCOPE
            + ")"
            ") freshness_at",
            params,
        ).fetchone()
        return row["freshness_at"] if row else None
