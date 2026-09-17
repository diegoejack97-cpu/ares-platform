# SQL strings remain complete for review.
# ruff: noqa: E501
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser


class ImpactDenied(Exception):
    pass


class ImpactService:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def authorize(self, db: psycopg.Connection[Any], user: AuthenticatedUser) -> None:
        if (
            user.role not in {"admin", "manager", "auditor"}
            or not db.execute(
                "select 1 from public.memberships m join public.tenant_entitlements e on e.tenant_id=m.tenant_id "
                "where m.tenant_id=%s and m.user_id=%s and m.active and m.role in ('admin','manager','auditor') "
                "and e.module='ares_connect' and e.status='active' and (e.expires_at is null or e.expires_at>now())",
                (user.tenant_id, user.user_id),
            ).fetchone()
        ):
            raise ImpactDenied

    def summary(self, user: AuthenticatedUser, days: int = 30) -> dict[str, Any]:
        if not 1 <= days <= 365:
            raise ValueError("invalid_window")
        until = datetime.now(UTC)
        since = until - timedelta(days=days)
        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            db.execute("set transaction isolation level repeatable read, read only")
            db.execute("set local statement_timeout='10s'")
            self.authorize(db, user)
            counts = db.execute(
                "select count(*) filter(where o.state<>'closed') as at_risk, "
                "count(*) filter(where exists(select 1 from public.ares_interventions i where i.tenant_id=o.tenant_id and i.opportunity_id=o.id and i.created_at>=%s and i.created_at<%s)) as worked "
                "from public.ares_opportunities o where o.tenant_id=%s and o.opened_at<%s",
                (since, until, user.tenant_id, until),
            ).fetchone()
            # Most recent outcome per opportunity prevents summing repeated observations.
            amounts = db.execute(
                "with latest as (select distinct on (opportunity_id) * from public.outcomes where tenant_id=%s and observed_at>=%s and observed_at<%s order by opportunity_id,observed_at desc,id desc) "
                "select currency,count(*) observations,count(*) filter(where source_ref='m6-synthetic-pilot') synthetic_observations,count(*) filter(where sale_value is not null) sales_observed, "
                "count(*) filter(where result_type='recovered') recovered,sum(sale_value) sale_value,"
                "sum(ares_influenced_value) filter(where attribution_level in ('influenced','incremental_proven')) ares_influenced_value,"
                "sum(incremental_value) filter(where attribution_level='incremental_proven' and nullif(trim(attribution_method),'') is not null) incremental_value,"
                "max(observed_at) freshness_at from latest group by currency order by currency nulls last",
                (user.tenant_id, since, until),
            ).fetchall()
            costs = db.execute(
                "select count(*) runs,count(u.cost_usd) measured_runs,sum(u.cost_usd) cost_usd "
                "from public.agent_runs r left join public.model_usage u on u.tenant_id=r.tenant_id and u.run_id=r.id "
                "where r.tenant_id=%s and r.started_at>=%s and r.started_at<%s",
                (user.tenant_id, since, until),
            ).fetchone()
        return {
            "window": {"since": since, "until": until, "days": days},
            "counts": counts,
            "amounts": amounts,
            "ai_cost": costs,
            "source": "Supabase/PostgreSQL — outcomes e trilha de intervenções",
            "computed_at": until,
            "definitions": [
                "Em risco: oportunidades abertas na data da consulta; não é uma reconstrução histórica.",
                "Trabalhadas: oportunidades com intervenção aberta no período.",
                "Valores: último outcome observado por oportunidade no período, separados por moeda.",
                "Recuperadas: último outcome com result_type=recovered. Venda observada exige sale_value informado.",
                "Valor influenciado não prova causalidade. Incremental permanece não comprovado sem método e evidência registrados.",
                "Custo de IA em USD: apenas uso medido; cobertura parcial quando há execuções sem custo observado.",
            ],
        }

    def interventions(
        self, user: AuthenticatedUser, days: int = 30, cursor: UUID | None = None, limit: int = 50
    ) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            self.authorize(db, user)
            rows = db.execute(
                "select i.id intervention_id,i.opportunity_id,i.correlation_id,i.status,i.state_before_ref,i.state_after_ref,i.created_at,i.closed_at,"
                "o.result_type,o.sale_value,o.ares_influenced_value,o.incremental_value,o.currency,o.attribution_level,o.attribution_method,o.observed_at "
                "from public.ares_interventions i left join lateral(select * from public.outcomes o where o.tenant_id=i.tenant_id and o.intervention_id=i.id order by observed_at desc,id desc limit 1) o on true "
                "where i.tenant_id=%s and i.created_at>=now()-(%s * interval '1 day') and (%s::uuid is null or i.id>%s) order by i.id limit %s",
                (user.tenant_id, days, cursor, cursor, limit + 1),
            ).fetchall()
        return {
            "items": rows[:limit],
            "next_cursor": rows[limit - 1]["intervention_id"] if len(rows) > limit else None,
        }

    def audit_export(self, user: AuthenticatedUser, format: str, days: int, rows: int) -> UUID:
        correlation = uuid4()
        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            self.authorize(db, user)
            db.execute(
                "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'human',%s,'report.export',%s,'ares:impact',%s)",
                (
                    user.tenant_id,
                    user.user_id,
                    correlation,
                    Jsonb({"format": format, "days": days, "rows": rows}),
                ),
            )
        return correlation
