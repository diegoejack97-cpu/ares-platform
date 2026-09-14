-- Journal-derived graph. Composite FKs prevent cross-tenant endpoints/evidence.
create index commercial_events_graph_lookup on public.commercial_events
  (tenant_id,aggregate_type,aggregate_id,occurred_at,id);
create table public.graph_nodes (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  kind text not null check (kind in ('opportunity','deal','company','contact')),
  ref_id uuid,
  external_ref text not null,
  label text not null,
  unique (tenant_id, id),
  unique (tenant_id, kind, external_ref)
);
create table public.graph_edges (
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  src_id uuid not null,
  dst_id uuid not null,
  kind text not null check (kind in ('concerns','company','contact')),
  evidence_event_id uuid not null,
  valid_from timestamptz not null,
  valid_until timestamptz,
  derivation_version text not null default 'journal-relationships.v1',
  primary key (tenant_id, src_id, dst_id, kind, evidence_event_id),
  foreign key (tenant_id, src_id) references public.graph_nodes(tenant_id,id),
  foreign key (tenant_id, dst_id) references public.graph_nodes(tenant_id,id),
  foreign key (tenant_id, evidence_event_id) references public.commercial_events(tenant_id,id),
  check (valid_until is null or valid_until >= valid_from)
);
create index graph_edges_active_source on public.graph_edges(tenant_id,src_id)
  where valid_until is null;
create index graph_edges_active_target on public.graph_edges(tenant_id,dst_id)
  where valid_until is null;
alter table public.graph_nodes enable row level security;
alter table public.graph_edges enable row level security;
create policy tenant_read_isolation on public.graph_nodes for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));
create policy tenant_read_isolation on public.graph_edges for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));
revoke all on public.graph_nodes, public.graph_edges from anon, authenticated;
grant select on public.graph_nodes, public.graph_edges to authenticated;
