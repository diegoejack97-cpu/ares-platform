"""Sole authorized query/snapshot reader. All amounts are calculated in PostgreSQL."""
# Complete SQL remains auditable.
# ruff: noqa: E501

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.intelligence.queries import QueryIntent

TOKEN_BUDGET = 2500
INSTRUCTION_RESERVE = 500
CONTENT_BUDGET = TOKEN_BUDGET - INSTRUCTION_RESERVE


class ContextUnavailable(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    # PostgreSQL JSONB reorders keys; the fingerprint must survive persistence.
    canonical = json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def project(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    # Never silently alter an aggregate. Omitted groups are explicitly recorded.
    result = json.loads(encode(payload))
    cuts = []
    while len(encode(result).encode()) > CONTENT_BUDGET:
        if result.get("matches"):
            result["matches"].pop()
            cuts.append("record")
        elif result.get("events"):
            result["events"].pop()
            cuts.append("event")
        elif result.get("metrics", {}).get("currencies"):
            result["metrics"]["currencies"].pop()
            cuts.append("currency_group")
        elif result.get("metrics", {}).get("stages"):
            result["metrics"]["stages"].pop()
            cuts.append("stage_group")
        elif result.get("details"):
            result.pop("details")
            cuts.append("details")
        else:
            raise ContextUnavailable("context_projection_too_large", 422)
    return result, cuts


class ContextBuilder:
    def memory(
        self, user: AuthenticatedUser, question: str, purpose: str = "chat", *, key: str = ""
    ) -> dict[str, Any]:
        from ares.knowledge.service import KnowledgeService

        return KnowledgeService(self.url, key).retrieve(user, question, purpose)

    @staticmethod
    def outcome_on(
        db: psycopg.Connection[Any], user: AuthenticatedUser, intervention: UUID
    ) -> dict[str, Any]:
        from ares.impact.evaluation import OutcomeService

        return OutcomeService.chain_on(db, user, intervention)

    @staticmethod
    def sentinel_context_on(
        db: psycopg.Connection[Any], tenant: UUID, event_id: UUID, finding_id: UUID, revision: int
    ) -> dict[str, Any]:
        """Service-scoped, closed snapshot. UI access is filtered by the finding API."""
        row = db.execute(
            "select * from public.sentinel_finding_events where tenant_id=%s and id=%s and finding_id=%s and revision=%s",
            (tenant, event_id, finding_id, revision),
        ).fetchone()
        if not row or fingerprint(row["snapshot_json"]) != row["content_hash"]:
            raise ContextUnavailable("sentinel_snapshot_invalid")
        snapshot = row["snapshot_json"]
        rule = snapshot.get("rule", {})
        content = {
            "finding": dict(snapshot["finding"]),
            "rule": {key: rule.get(key) for key in ("kind", "threshold_hours", "title")},
        }
        cuts = []
        if len(encode(content).encode()) > CONTENT_BUDGET:
            content["finding"].pop("title", None)
            cuts.append("Título omitido para respeitar o orçamento de contexto.")
        if len(encode(content).encode()) > CONTENT_BUDGET:
            raise ContextUnavailable("sentinel_snapshot_too_large")
        return {
            "context_ref": row["id"],
            "content": encode(content),
            "content_hash": fingerprint(content),
            "evidence_refs": [str(row["id"])],
            "cuts": cuts,
        }

    def __init__(self, database_url: str):
        self.url = database_url

    def portfolio(
        self, user: AuthenticatedUser, criterion: str, currency: str | None
    ) -> dict[str, Any]:
        intent = QueryIntent.model_validate(
            {
                "open_only": True,
                "order": criterion,
                "currency": currency,
                "sample_limit": 20,
                "fields": [
                    "title",
                    "stage",
                    "value",
                    "currency",
                    "priority",
                    "opportunity",
                    "score",
                    "sla",
                ],
            }
        )
        source = self.build(user, intent, purpose="portfolio_analysis")
        content = json.loads(source["content"])
        matches = content.get("matches", [])
        # Only a Core opportunity can become an intervention. Missing coverage stays explicit.
        content["matches"] = [
            dict(item, id=item["opportunity_id"]) for item in matches if item.get("opportunity_id")
        ]
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authorize(db, user)
            if role == "seller":
                owned = {
                    str(r["id"])
                    for r in db.execute(
                        "select id from public.ares_opportunities where tenant_id=%s and owner_user_id=%s",
                        (user.tenant_id, user.user_id),
                    )
                }
                content["matches"] = [r for r in content["matches"] if str(r["id"]) in owned]
        content["criterion"] = criterion
        content["limitations"] = [
            "Amostra selecionada sobre todo o espelho autorizado; sincronização do CRM não homologada.",
            "Negócios sem oportunidade ARES não podem receber intervenção nesta seleção.",
        ]
        while len(encode(content).encode()) > CONTENT_BUDGET and content["matches"]:
            content["matches"].pop()
        if len(encode(content).encode()) > CONTENT_BUDGET:
            raise ContextUnavailable("portfolio_context_too_large", 422)
        relevant = {
            "criterion": criterion,
            "currency": currency,
            "metrics": source["result"].get("metrics"),
            "candidates": source["result"].get("matches"),
        }

        # Ignore capture/update timestamps and self-owned decision state transitions.
        def meaningful(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    k: meaningful(v)
                    for k, v in value.items()
                    if k
                    not in {
                        "updated_at",
                        "source_changed_at",
                        "newest_source_change",
                        "opportunity_state",
                    }
                }
            if isinstance(value, list):
                return [meaningful(v) for v in value]
            return value

        source["relevant_hash"] = fingerprint(meaningful(relevant))
        source["content"] = encode(content)
        source["content_hash"] = fingerprint(content)
        source["candidate_refs"] = [str(item["id"]) for item in content["matches"]]
        source["metadata"]["selected_candidates"] = len(content["matches"])
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute(
                "update public.context_snapshots set content_json=%s,content_hash=%s,token_estimate=%s,metadata_json=%s where tenant_id=%s and actor_id=%s and id=%s and purpose='portfolio_analysis'",
                (
                    Jsonb(content),
                    source["content_hash"],
                    len(encode(content).encode()) + INSTRUCTION_RESERVE,
                    Jsonb(json.loads(encode(source["metadata"]))),
                    user.tenant_id,
                    user.user_id,
                    source["context_ref"],
                ),
            )
        return source

    def timezone(self, user: AuthenticatedUser) -> str:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authorize(db, user)
            row = db.execute(
                "select timezone from public.tenants where id=%s", (user.tenant_id,)
            ).fetchone()
            assert row
            return str(row["timezone"])

    @staticmethod
    def legacy_snapshot_on(
        db: psycopg.Connection[Any], tenant: UUID, opportunity: UUID, context: UUID | None = None
    ) -> dict[str, Any] | None:
        row = db.execute(
            "select * from public.context_snapshots where tenant_id=%s and opportunity_id=%s and actor_id is null order by snapshot_version desc limit 1",
            (tenant, opportunity),
        ).fetchone()
        if not row or (context is not None and row["id"] != context):
            return None
        return dict(row)

    @staticmethod
    def legacy_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
        from ares.intelligence.chat_context import bounded_context

        result = bounded_context(
            {
                "context_ref": str(snapshot["id"]),
                "facts": snapshot["facts_json"],
                "citations": snapshot["citations_json"],
                "captured_at": snapshot["captured_at"],
            },
            CONTENT_BUDGET,
        )
        result["tokens_upper_bound"] += INSTRUCTION_RESERVE
        result["token_limit"] = TOKEN_BUDGET
        result["instruction_reserve"] = INSTRUCTION_RESERVE
        return result

    @staticmethod
    def specialist_projection_on(
        db: psycopg.Connection[Any], tenant: UUID, opportunity: UUID, context: UUID | None = None
    ) -> dict[str, Any]:
        snapshot = db.execute(
            "select * from public.context_snapshots where tenant_id=%s and opportunity_id=%s and actor_id is null "
            + ("and id=%s " if context else "")
            + "order by snapshot_version desc limit 1",
            (tenant, opportunity, context) if context else (tenant, opportunity),
        ).fetchone()
        opp = db.execute(
            "select id,deal_id,state,score,priority,owner_user_id,sla_at from public.ares_opportunities where tenant_id=%s and id=%s",
            (tenant, opportunity),
        ).fetchone()
        if not snapshot or not opp:
            raise ContextUnavailable("context_not_found", 404)
        deal = None
        if opp["deal_id"]:
            deal = db.execute(
                "select id,title,status,value,currency,canonical_stage,external_stage,owner_user_id from public.deals where tenant_id=%s and id=%s",
                (tenant, opp["deal_id"]),
            ).fetchone()
        signals = db.execute(
            "select id,event_id,signal_type,rule_id,rule_version,severity,evidence from public.signals where tenant_id=%s and opportunity_id=%s order by severity desc,id",
            (tenant, opportunity),
        ).fetchall()
        state = dict(opp)
        state.pop("deal_id")
        if state["state"] in {"prioritized", "awaiting_decision"}:
            state["state"] = "open_for_decision"
        # No captured_at/event backlog/update timestamp in the relevant fingerprint.
        facts = {
            "opportunity": state,
            "deal": dict(deal) if deal else snapshot["facts_json"].get("deal", {}),
            "signals": [dict(row) for row in signals],
        }
        relevant_hash = fingerprint(facts)
        projection = json.loads(encode(facts))
        cuts = 0
        while len(encode(projection).encode()) > CONTENT_BUDGET and projection["signals"]:
            projection["signals"].pop()
            cuts += 1
        if len(encode(projection).encode()) > CONTENT_BUDGET:
            raise ContextUnavailable("context_projection_too_large", 422)
        refs = [str(item["event_id"]) for item in projection["signals"]]
        return {
            "context_ref": snapshot["id"],
            "content": encode(projection),
            "content_hash": fingerprint(projection),
            "relevant_hash": relevant_hash,
            "evidence_refs": list(dict.fromkeys(refs))[:20],
            "truncated": bool(cuts),
            "tokens_upper_bound": len(encode(projection).encode()) + INSTRUCTION_RESERVE,
        }

    @staticmethod
    def authorize(db: psycopg.Connection[Any], user: AuthenticatedUser) -> str:
        row = db.execute(
            "select m.role::text role from public.memberships m join public.tenants t on t.id=m.tenant_id where m.tenant_id=%s and m.user_id=%s and m.active and t.status='active' and exists(select 1 from public.tenant_entitlements e where e.tenant_id=m.tenant_id and e.module='ares_connect' and e.status='active' and (e.expires_at is null or e.expires_at>clock_timestamp()))",
            (user.tenant_id, user.user_id),
        ).fetchone()
        if not row:
            raise ContextUnavailable("context_access_denied", 403)
        return str(row["role"])

    @staticmethod
    def version(db: psycopg.Connection[Any], tenant: UUID) -> int:
        row = db.execute(
            "select version from private.context_data_versions where tenant_id=%s", (tenant,)
        ).fetchone()
        return int(row["version"]) if row else 0

    def build(
        self, user: AuthenticatedUser, intent: QueryIntent, *, purpose: str = "commercial_analysis"
    ) -> dict[str, Any]:
        if purpose not in {"commercial_analysis", "chat", "agent_analysis", "portfolio_analysis"}:
            raise ContextUnavailable("context_purpose_invalid", 422)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute("set local statement_timeout='5s'")
            role = self.authorize(db, user)
            if role == "seller" and intent.owner_id not in {None, user.user_id}:
                raise ContextUnavailable("context_scope_denied", 403)
            if role == "seller" and intent.entity == "sentinel":
                raise ContextUnavailable("context_scope_denied", 403)
            version = self.version(db, user.tenant_id)
            access = fingerprint(
                [
                    str(user.tenant_id),
                    str(user.user_id),
                    role,
                    "own_portfolio" if role == "seller" else "tenant",
                ]
            )
            key = fingerprint([purpose, intent.model_dump(mode="json"), access, version])
            cached = db.execute(
                "select * from public.context_snapshots where tenant_id=%s and actor_id=%s and cache_key=%s and valid_until>clock_timestamp() order by captured_at desc limit 1",
                (user.tenant_id, user.user_id, key),
            ).fetchone()
            if cached:
                return self._public(cached, cache_hit=True)
            if intent.entity in {"portfolio", "deal"}:
                payload, citations, sources = self._commercial(db, user, role, intent)
            else:
                payload, citations, sources = self._entity(db, user, role, intent)
            # Under READ COMMITTED a concurrent committed change invalidates the
            # assembled view. In a caller's repeatable transaction it stays stable.
            if version != self.version(db, user.tenant_id) or role != self.authorize(db, user):
                raise ContextUnavailable("context_changed_during_query")
            projection, cuts = project(payload)
            captured = datetime.now(UTC)
            selected = {str(item.get("id")) for item in projection.get("matches", [])}
            event_ids = {str(item.get("id")) for item in projection.get("events", [])}
            projected_citations = [
                item
                for item in citations
                if (item.get("kind") == "record" and str(item.get("record_id")) in selected)
                or (item.get("kind") == "event" and str(item.get("event_id")) in event_ids)
                or item.get("kind") == "aggregate"
            ]
            metadata = {
                "schema_version": "trusted-context.v1",
                "purpose": purpose,
                "query": intent.model_dump(mode="json"),
                "scope": "own_portfolio" if role == "seller" else "tenant",
                "role": role,
                "access_hash": access,
                "data_version": version,
                "sources": sources,
                "count_method": "utf8_bytes_upper_bound",
                "token_budget": TOKEN_BUDGET,
                "instruction_reserve": INSTRUCTION_RESERVE,
                "content_tokens_upper_bound": len(encode(projection).encode()),
                "cuts": cuts,
                "sample_count": len(projection.get("matches", [])),
                "sample_limit": intent.sample_limit,
                "mirror_query_complete": True,
                "crm_sync_complete": False,
                "period": {
                    "since": intent.since,
                    "until": intent.until,
                    "field": intent.date_field,
                    "bounds": "[since,until)",
                },
                "definitions": {
                    "total": "Negócios distintos do espelho que satisfazem o filtro e acesso atuais.",
                    "currency_totals": "Valores salvos separados por moeda, sem conversão.",
                    "changes": "Transições de etapa registradas, no período informado, para o universo filtrado.",
                },
            }
            row = db.execute(
                "insert into public.context_snapshots(id,tenant_id,opportunity_id,snapshot_version,opportunity_state,facts_json,citations_json,token_estimate,content_hash,source,source_ref,captured_at,actor_id,purpose,scope_kind,scope_ref,query_json,metadata_json,content_json,access_hash,data_version,cache_key,valid_until,truncated,token_budget) values(%s,%s,null,1,'read_only',%s,%s,%s,%s,'ares','context-builder:v1',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2500) returning *",
                (
                    uuid4(),
                    user.tenant_id,
                    Jsonb(json.loads(encode(payload))),
                    Jsonb(json.loads(encode(projected_citations))),
                    len(encode(projection).encode()) + INSTRUCTION_RESERVE,
                    fingerprint(projection),
                    captured,
                    user.user_id,
                    purpose,
                    intent.entity,
                    intent.scope_ref,
                    Jsonb(intent.model_dump(mode="json")),
                    Jsonb(json.loads(encode(metadata))),
                    Jsonb(projection),
                    access,
                    version,
                    key,
                    captured + timedelta(seconds=60),
                    bool(cuts or payload.get("sample_truncated")),
                ),
            ).fetchone()
            assert row
            return self._public(row, cache_hit=False)

    def read(self, user: AuthenticatedUser, context_ref: UUID) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authorize(db, user)
            row = db.execute(
                "select * from public.context_snapshots where tenant_id=%s and actor_id=%s and id=%s",
                (user.tenant_id, user.user_id, context_ref),
            ).fetchone()
            if not row:
                raise ContextUnavailable("context_not_found", 404)
            access = fingerprint(
                [
                    str(user.tenant_id),
                    str(user.user_id),
                    role,
                    "own_portfolio" if role == "seller" else "tenant",
                ]
            )
            if (
                row["valid_until"] <= datetime.now(UTC)
                or row["data_version"] != self.version(db, user.tenant_id)
                or row["access_hash"] != access
            ):
                raise ContextUnavailable("context_stale")
            return self._public(row, cache_hit=True)

    @staticmethod
    def _public(row: dict[str, Any], *, cache_hit: bool) -> dict[str, Any]:
        metadata = row["metadata_json"]
        return {
            "context_ref": str(row["id"]),
            "content": encode(row["content_json"]),
            "content_hash": row["content_hash"],
            "captured_at": row["captured_at"],
            "valid_until": row["valid_until"],
            "citations": row["citations_json"],
            "tokens_upper_bound": row["token_estimate"],
            "token_limit": row["token_budget"],
            "count_method": metadata["count_method"],
            "truncated": row["truncated"],
            "source": {
                "sentinel": "Regras ARES",
                "intervention": "Intervenções e Event Journal",
                "opportunity": "Banco ARES e Event Journal",
            }.get(row["scope_kind"], "Banco ARES (espelho do CRM)"),
            "metadata": metadata,
            "result": row["facts_json"],
            "cache_hit": cache_hit,
        }

    @staticmethod
    def _commercial(
        db: psycopg.Connection[Any], user: AuthenticatedUser, role: str, intent: QueryIntent
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        clauses = [
            "d.tenant_id=%s",
            "not d.is_missing",
            "(d.connection_id is null or exists(select 1 from public.connections c where c.tenant_id=d.tenant_id and c.id=d.connection_id and c.status<>'revoked'))",
        ]
        params: list[Any] = [user.tenant_id]
        if role == "seller":
            clauses.append(
                "(d.owner_user_id=%s or exists(select 1 from public.ares_opportunities own where own.tenant_id=d.tenant_id and own.deal_id=d.id and own.owner_user_id=%s))"
            )
            params.extend([user.user_id, user.user_id])
        if intent.owner_id:
            clauses.append("d.owner_user_id=%s")
            params.append(intent.owner_id)
        for column, value in [
            ("d.connection_id", intent.connection_id),
            ("d.currency", intent.currency),
        ]:
            if value is not None:
                clauses.append(f"{column}=%s")
                params.append(value)
        if intent.scope_ref:
            clauses.append("d.id=%s")
            params.append(intent.scope_ref)
        if intent.stages:
            clauses.append("d.normalized_stage=any(%s)")
            params.append(intent.stages)
        if intent.open_only:
            clauses.append(
                "d.status='open' and coalesce(d.canonical_stage,d.external_stage,'') not in ('won','lost','ganho','perdido')"
            )
        if intent.name:
            clauses.append(
                "(translate(lower(d.title),'áàâãäéèêëíìîïóòôõöúùûüç','aaaaaeeeeiiiiooooouuuuc') like %s escape '' or d.id::text=%s or coalesce(d.external_ref->>'id',d.external_id)=%s or o.id::text=%s)"
            )
            from ares.chat.search import normalize

            params.extend(
                [
                    "%" + normalize(intent.name).replace("%", "").replace("_", "") + "%",
                    intent.name,
                    intent.name,
                    intent.name,
                ]
            )
        if intent.references is not None:
            clauses.append(
                "(d.id::text=any(%s) or coalesce(d.external_ref->>'id',d.external_id)=any(%s) or o.id::text=any(%s))"
            )
            params.extend([intent.references] * 3)
        if intent.since:
            column = {"created": "d.created_at", "changed": "d.source_changed_at"}[
                intent.date_field
            ]
            clauses.append(f"{column}>=%s and {column}<%s")
            params.extend([intent.since, intent.until])
        cte = (
            """with candidates as (
          select d.*,o.id opportunity_id,o.state opportunity_state,o.priority,o.score,o.sla_at,
            case translate(lower(coalesce(d.canonical_stage,d.external_stage,'')),
              'áàâãäéèêëíìîïóòôõöúùûüç','aaaaaeeeeiiiiooooouuuuc')
              when 'entrada' then 'new' when 'qualificacao' then 'qualification'
              when 'proposta' then 'proposal' when 'negociacao' then 'negotiation'
              when 'ganho' then 'won' when 'perdido' then 'lost'
              else nullif(coalesce(d.canonical_stage,d.external_stage),'') end normalized_stage,
            count(*) over(partition by d.tenant_id,d.connection_id,coalesce(d.external_ref->>'id',d.external_id,d.id::text)) identity_rows,
            row_number() over(partition by d.tenant_id,d.connection_id,coalesce(d.external_ref->>'id',d.external_id,d.id::text)
              order by (d.external_id like d.connection_id::text||':%%') desc nulls last,d.source_changed_at desc nulls last,d.updated_at desc,d.id) identity_rank
          from public.deals d left join lateral (
            select id,state,priority,score,sla_at from public.ares_opportunities
            where tenant_id=d.tenant_id and deal_id=d.id
            order by updated_at desc,id limit 1) o on true
          where d.tenant_id=%s) , scoped as (select * from candidates d where identity_rank=1 and """
            + " and ".join(clauses).replace("o.id::text", "d.opportunity_id::text")
            + ") "
        )
        params = [user.tenant_id, *params]
        summary = db.execute(
            cte
            + "select count(*) total,coalesce(sum(identity_rows-1),0)::bigint duplicate_rows,count(*) filter(where value is null) missing_value,count(*) filter(where currency is null) missing_currency,count(*) filter(where coalesce(canonical_stage,external_stage) is null) missing_stage,count(*) filter(where owner_user_id is null) missing_owner,count(*) filter(where sla_at<clock_timestamp() and opportunity_state<>'closed') overdue,max(source_changed_at) newest_source_change from scoped",
            params,
        ).fetchone()
        currencies = db.execute(
            cte
            + "select currency,count(*) records,count(value) valued_records,sum(value) value from scoped group by currency order by currency nulls last",
            params,
        ).fetchall()
        stages = db.execute(
            cte
            + "select normalized_stage stage,count(*) records from scoped group by normalized_stage order by normalized_stage nulls last",
            params,
        ).fetchall()
        changes = None
        if intent.since:
            change_row = db.execute(
                cte
                + "select count(*) changes from public.deal_stage_history h join scoped d on d.tenant_id=h.tenant_id and d.id=h.deal_id where h.occurred_at>=%s and h.occurred_at<%s",
                [*params, intent.since, intent.until],
            ).fetchone()
            assert change_row is not None
            changes = change_row["changes"]
        missing_dates = 0
        if intent.since:
            without_window = cte.replace(" and " + clauses[-1], "")
            missing = db.execute(
                without_window
                + f"select count(*) missing_dates from scoped where {column.replace('d.', '')} is null",
                params[:-2],
            ).fetchone()
            assert missing
            missing_dates = missing["missing_dates"]
        order = {
            "recent": "updated_at desc,id",
            "value": "value desc nulls last,id",
            "lowest_value": "value asc nulls last,id",
            "urgency": "priority asc nulls last,score desc nulls last,id",
            "deadline": "sla_at asc nulls last,priority asc nulls last,id",
            "attractiveness": "score desc nulls last,priority asc nulls last,id",
        }[intent.order]
        rows = db.execute(
            cte
            + "select id,title,normalized_stage canonical_stage,external_stage,status,value,currency,connection_id,coalesce(external_ref->>'id',external_id) external_id,owner_user_id,opportunity_id,opportunity_state,priority,score,sla_at,source_changed_at,updated_at from scoped order by "
            + order
            + " limit %s",
            [*params, intent.sample_limit],
        ).fetchall()
        if intent.order in {"value", "lowest_value"} and len(currencies) > 1:
            rows = db.execute(
                cte
                + ", ranked as (select *,row_number() over(partition by currency order by "
                + order
                + ") currency_rank from scoped) select id,title,normalized_stage canonical_stage,external_stage,status,value,currency,connection_id,coalesce(external_ref->>'id',external_id) external_id,owner_user_id,opportunity_id,opportunity_state,priority,score,sla_at,source_changed_at,updated_at from ranked order by (currency_rank=1) desc,currency nulls last,"
                + order
                + " limit %s",
                [*params, intent.sample_limit],
            ).fetchall()
        if intent.entity == "deal" and not rows:
            raise ContextUnavailable("context_not_found", 404)
        sources = db.execute(
            "select c.id connection_id,c.provider,c.status,c.last_sync_at,s.watermark,s.last_completed_at,s.cursor pending_cursor,(select count(*) from public.jobs j where j.tenant_id=c.tenant_id and j.payload->>'connection_id'=c.id::text and j.kind='integration.sync' and j.status in ('queued','running')) active_sync_jobs from public.connections c left join public.sync_cursors s on s.tenant_id=c.tenant_id and s.connection_id=c.id and s.entity_type='deal' where c.tenant_id=%s and (%s::uuid is null or c.id=%s) order by c.id",
            (user.tenant_id, intent.connection_id, intent.connection_id),
        ).fetchall()
        sources = [
            {**dict(source), "coverage": "unknown", "crm_complete": False} for source in sources
        ]
        metrics = {
            **dict(summary or {}),
            "currencies": [dict(r) for r in currencies],
            "stages": [dict(r) for r in stages],
            "changes": changes,
            "excluded_unknown_dates": missing_dates,
        }
        limitations = [
            "Totais do espelho autorizado; a completude da sincronização do CRM não foi comprovada."
        ]
        if not sources:
            limitations.append("Nenhuma conexão CRM registrada; consulta limitada ao banco ARES.")
        if any(
            source["status"] not in {"active", "configured", "connected"}
            or source["last_completed_at"] is None
            or source["pending_cursor"]
            or source["active_sync_jobs"]
            for source in sources
        ):
            limitations.append(
                "Sincronização não confirmada, indisponível ou pendente; os dados podem estar desatualizados."
            )
        if metrics["duplicate_rows"]:
            limitations.append(
                "Duplicados da mesma identidade foram reconciliados; nomes de conexões diferentes não foram fundidos."
            )
        if missing_dates:
            limitations.append(
                f"{missing_dates} negócios sem a data exigida foram excluídos do período; não é prova de ausência de negócios nessa janela."
            )
        matches = []
        for row in rows:
            item = {"id": row["id"], "source": "Banco ARES"}
            if "title" in intent.fields:
                item["title"] = str(row["title"])[:160]
            if "stage" in intent.fields:
                item["external_stage"] = row["external_stage"]
                item["canonical_stage"] = row["canonical_stage"]
            for field, column in [
                ("value", "value"),
                ("currency", "currency"),
                ("owner", "owner_user_id"),
                ("priority", "priority"),
                ("opportunity", "opportunity_id"),
                ("score", "score"),
                ("sla", "sla_at"),
            ]:
                if field in intent.fields:
                    item[column] = row[column]
            matches.append(item)
        payload = {
            "matches": matches,
            "metrics": metrics,
            "limitations": limitations,
            "criterion": intent.order if intent.order != "recent" else None,
            "currencies": [r["currency"] for r in currencies],
            "sample_truncated": len(rows) < metrics["total"],
        }
        if (
            rows
            and len(currencies) == 1
            and currencies[0]["currency"]
            and intent.order in {"value", "lowest_value", "urgency"}
        ):
            payload["selection"] = str(rows[0]["id"])
        citations = [
            {
                "kind": "record",
                "record_id": str(row["id"]),
                "event_id": str(row["id"]),
                "event_type": "database.deal.read",
                "source": "Banco ARES",
                "source_ref": f"{user.tenant_id}/{row['connection_id']}/{row['external_id'] or row['id']}",
                "occurred_at": row["source_changed_at"] or row["updated_at"],
            }
            for row in rows
        ]
        citations.append(
            {
                "kind": "aggregate",
                "event_id": "query:" + fingerprint(intent.model_dump(mode="json")),
                "event_type": "database.aggregate.read",
                "source": "PostgreSQL",
                "source_ref": "commercial-query.v1",
                "occurred_at": datetime.now(UTC),
            }
        )
        return payload, citations, sources

    @staticmethod
    def _entity(
        db: psycopg.Connection[Any], user: AuthenticatedUser, role: str, intent: QueryIntent
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        if intent.entity == "sentinel":
            row = db.execute(
                "select rule_id,title,kind,threshold_hours,interval_minutes,start_time_local,next_run_at,last_run_at,enabled,version,updated_at from public.sentinel_schedules where tenant_id=%s and rule_id=%s",
                (user.tenant_id, intent.rule_id),
            ).fetchone()
            if not row:
                raise ContextUnavailable("context_not_found", 404)
            return (
                {
                    "details": dict(row),
                    "matches": [],
                    "limitations": ["Regra configurada, não prova de um achado ou de execução."],
                },
                [],
                [{"source": "sentinel_schedules", "ref": intent.rule_id}],
            )
        opportunity = intent.scope_ref
        assert opportunity is not None
        intervention = None
        if intent.entity == "intervention":
            intervention = db.execute(
                "select id,opportunity_id,status,state_before_ref,state_after_ref,created_at,closed_at from public.ares_interventions where tenant_id=%s and id=%s",
                (user.tenant_id, intent.scope_ref),
            ).fetchone()
            if not intervention:
                raise ContextUnavailable("context_not_found", 404)
            opportunity = intervention["opportunity_id"]
        row = db.execute(
            "select id,deal_id,state,score,priority,owner_user_id,sla_at,updated_at from public.ares_opportunities where tenant_id=%s and id=%s and (%s or owner_user_id=%s)",
            (user.tenant_id, opportunity, role != "seller", user.user_id),
        ).fetchone()
        if not row:
            raise ContextUnavailable("context_not_found", 404)
        snapshot = ContextBuilder.legacy_snapshot_on(db, user.tenant_id, opportunity)
        events = snapshot["facts_json"].get("events", []) if snapshot else []
        details: dict[str, Any] = {
            "opportunity": dict(row),
            "intervention": dict(intervention) if intervention else None,
        }
        if intervention:
            details["observed_states"] = [
                dict(item)
                for item in db.execute(
                    "select id,captured_at,content_hash,opportunity_state from public.context_snapshots where tenant_id=%s and id=any(%s)",
                    (
                        user.tenant_id,
                        [intervention["state_before_ref"], intervention["state_after_ref"]],
                    ),
                ).fetchall()
            ]
            details["outcomes"] = [
                dict(item)
                for item in db.execute(
                    "select id,result_type,attribution_level,sale_value,ares_influenced_value,incremental_value,currency,observed_at from public.outcomes where tenant_id=%s and intervention_id=%s order by observed_at desc limit 8",
                    (user.tenant_id, intervention["id"]),
                ).fetchall()
            ]
        matches = []
        if row["deal_id"]:
            payload, citations, sources = ContextBuilder._commercial(
                db, user, role, QueryIntent(entity="deal", scope_ref=row["deal_id"])
            )
            matches = payload["matches"]
        else:
            citations, sources = [], []
        citations.extend(
            {"kind": "event", **dict(item)}
            for item in (snapshot["citations_json"] if snapshot else [])
        )
        if snapshot:
            sources.append(
                {
                    "source": "Event Journal",
                    "context_ref": str(snapshot["id"]),
                    "captured_at": snapshot["captured_at"],
                    "content_hash": snapshot["content_hash"],
                    "snapshot_version": snapshot["snapshot_version"],
                }
            )
        return (
            {
                "matches": matches,
                "details": details,
                "events": events,
                "limitations": [] if snapshot else ["Sem snapshot episódico salvo."],
            },
            citations,
            sources,
        )
