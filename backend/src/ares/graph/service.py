from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.graph.projector import node_id


class GraphUnavailable(Exception):
    pass


class GraphService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def read(self, user: AuthenticatedUser, opportunity: UUID, depth: int = 2) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            db.execute("set transaction isolation level repeatable read, read only")
            db.execute("set local statement_timeout='5s'")
            return self.read_on(db, user, opportunity, depth)

    def read_on(
        self,
        db: psycopg.Connection[Any],
        user: AuthenticatedUser,
        opportunity: UUID,
        depth: int = 2,
    ) -> dict[str, Any]:
        if depth not in (1, 2):
            raise ValueError("invalid_graph_depth")
        allowed = db.execute(
            "select o.id from public.ares_opportunities o "
            "join public.tenants t on t.id=o.tenant_id "
            "join public.memberships m on m.tenant_id=o.tenant_id and m.user_id=%s "
            "where o.tenant_id=%s and o.id=%s and m.active and t.status='active' "
            "and exists(select 1 from public.tenant_entitlements e where e.tenant_id=o.tenant_id "
            "and e.module='ares_connect' and e.status='active' "
            "and (e.expires_at is null or e.expires_at>now()))",
            (user.user_id, user.tenant_id, opportunity),
        ).fetchone()
        if not allowed:
            raise GraphUnavailable
        root = node_id(user.tenant_id, "opportunity", str(opportunity))
        rows = db.execute(
            """
            with recursive walk as (
              select e.*, 1 as depth, array[e.src_id,e.dst_id] as path
              from public.graph_edges e where e.tenant_id=%s and e.src_id=%s
                and e.valid_until is null
              union all
              select e.*, w.depth+1, w.path || e.dst_id from walk w
              join public.graph_edges e on e.tenant_id=w.tenant_id and e.src_id=w.dst_id
              where w.depth < %s and e.valid_until is null and not e.dst_id=any(w.path)
            )
            select w.src_id,w.dst_id,w.kind,w.evidence_event_id,w.valid_from,w.depth,
              e.event_type,e.source,e.occurred_at,w.derivation_version
            from walk w join public.commercial_events e
              on e.tenant_id=w.tenant_id and e.id=w.evidence_event_id
            order by w.depth,w.kind,w.dst_id,w.evidence_event_id limit 9
            """,
            (user.tenant_id, root, depth),
        ).fetchall()
        edges = [dict(row) for row in rows[:8]]
        ids = {root} | {edge[key] for edge in edges for key in ("src_id", "dst_id")}
        nodes = db.execute(
            "select id,kind,label,external_ref from public.graph_nodes "
            "where tenant_id=%s and id=any(%s) order by kind,id",
            (user.tenant_id, list(ids)),
        ).fetchall()
        return {
            "root_id": root,
            "nodes": [dict(row) for row in nodes],
            "edges": edges,
            "depth": depth,
            "edge_limit": 8,
            "truncated": len(rows) > 8,
            "source": "Event Journal",
            "freshness_at": datetime.now(UTC),
            "period": "current_relationships",
            "derivation_version": "journal-relationships.v1",
        }
