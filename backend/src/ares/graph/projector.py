from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg


def node_id(tenant: UUID, kind: str, ref: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"ares:graph:{tenant}:{kind}:{ref}")


def relationships(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replay in event time, stable UUID tie-break. Absent fields do not erase facts."""
    edges: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=lambda e: (e["occurred_at"], str(e["id"]))):
        for kind in ("company", "contact"):
            field = f"{kind}_id"
            if field not in event["data"]:
                continue
            value = event["data"][field]
            # Malformed source fields are not evidence of either a relationship or removal.
            if value is not None and (
                not isinstance(value, str) or not value.strip() or len(value) > 200
            ):
                continue
            previous = active.pop(kind, None)
            if previous is not None:
                previous["valid_until"] = event["occurred_at"]
            if value is not None:
                edge = {
                    "kind": kind,
                    "ref": value,
                    "evidence_event_id": event["id"],
                    "valid_from": event["occurred_at"],
                    "valid_until": None,
                }
                edges.append(edge)
                active[kind] = edge
    return edges


def project_opportunity(db: psycopg.Connection[Any], tenant: UUID, opportunity_id: UUID) -> None:
    # Opportunities share deal edges. Serialize tenant projections, including late events.
    db.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"graph:{tenant}",))
    opportunity = db.execute(
        "select o.id,d.id as deal_id,d.external_id from public.ares_opportunities o "
        "join public.deals d on d.tenant_id=o.tenant_id and d.id=o.deal_id "
        "where o.tenant_id=%s and o.id=%s",
        (tenant, opportunity_id),
    ).fetchone()
    if opportunity is None:
        return
    events = db.execute(
        "select id,occurred_at,data from public.commercial_events "
        "where tenant_id=%s and aggregate_type='deal' and aggregate_id=%s "
        "order by occurred_at,id",
        (tenant, opportunity["external_id"]),
    ).fetchall()
    if not events:
        return

    def node(kind: str, ref: str, canonical: UUID | None = None) -> UUID:
        identifier = node_id(tenant, kind, ref)
        # Labels are identifiers, not copied message bodies or invented subject names.
        label = {
            "opportunity": "Oportunidade ARES",
            "deal": "Negócio CRM",
            "company": "Empresa CRM",
            "contact": "Contato CRM",
        }[kind]
        db.execute(
            "insert into public.graph_nodes(id,tenant_id,kind,ref_id,external_ref,label) "
            "values(%s,%s,%s,%s,%s,%s) on conflict (id) do nothing",
            (identifier, tenant, kind, canonical, ref, label),
        )
        return identifier

    def edge(
        src: UUID, dst: UUID, kind: str, event: UUID, start: datetime, end: datetime | None
    ) -> None:
        db.execute(
            "insert into public.graph_edges(tenant_id,src_id,dst_id,kind,evidence_event_id,"
            "valid_from,valid_until) values(%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (tenant_id,src_id,dst_id,kind,evidence_event_id) "
            "do update set valid_until=excluded.valid_until",
            (tenant, src, dst, kind, event, start, end),
        )

    root = node("opportunity", str(opportunity_id), opportunity_id)
    deal = node("deal", str(opportunity["deal_id"]), opportunity["deal_id"])
    # A relation to an ARES opportunity needs its own recorded signal, not just a CRM event.
    evidence = db.execute(
        "select distinct e.id,e.occurred_at from public.signals s join public.commercial_events e "
        "on e.tenant_id=s.tenant_id and e.id=s.event_id "
        "where s.tenant_id=%s and s.opportunity_id=%s order by e.occurred_at,e.id",
        (tenant, opportunity_id),
    ).fetchall()
    # Derive every evidence interval from the journal so fresh and incremental replay agree.
    for index, signal in enumerate(evidence):
        end = evidence[index + 1]["occurred_at"] if index + 1 < len(evidence) else None
        edge(root, deal, "concerns", signal["id"], signal["occurred_at"], end)
    for relation in relationships([dict(e) for e in events]):
        target = node(relation["kind"], relation["ref"])
        edge(
            deal,
            target,
            relation["kind"],
            relation["evidence_event_id"],
            relation["valid_from"],
            relation["valid_until"],
        )


def project_event(db: psycopg.Connection[Any], tenant: UUID, event_id: UUID) -> None:
    rows = db.execute(
        "select o.id from public.commercial_events e join public.deals d "
        "on d.tenant_id=e.tenant_id and d.external_id=e.aggregate_id "
        "join public.ares_opportunities o on o.tenant_id=d.tenant_id and o.deal_id=d.id "
        "where e.tenant_id=%s and e.id=%s and e.aggregate_type='deal' order by o.id",
        (tenant, event_id),
    ).fetchall()
    for row in rows:
        project_opportunity(db, tenant, row["id"])
