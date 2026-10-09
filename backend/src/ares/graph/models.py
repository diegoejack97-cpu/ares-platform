from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: UUID
    kind: str
    label: str
    external_ref: str


class GraphEdge(BaseModel):
    src_id: UUID
    dst_id: UUID
    kind: str
    evidence_event_id: UUID
    valid_from: datetime
    depth: int
    event_type: str
    source: str
    occurred_at: datetime
    derivation_version: str


class OpportunityGraph(BaseModel):
    root_id: UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    depth: int
    edge_limit: int
    truncated: bool
    source: str
    freshness_at: datetime
    period: str
    derivation_version: str
