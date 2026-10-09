create table public.signals (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  event_id uuid not null,
  opportunity_id uuid,
  signal_type text not null,
  rule_id text not null,
  rule_version text not null,
  severity smallint not null check (severity between 1 and 5),
  confidence numeric(5, 4) not null default 1 check (confidence between 0 and 1),
  evidence jsonb not null default '{}'::jsonb,
  detected_at timestamptz not null default now(),
  correlation_id uuid not null,
  source public.source_kind not null default 'ares',
  source_ref text,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, event_id, rule_id, rule_version),
  foreign key (tenant_id, event_id)
    references public.commercial_events(tenant_id, id) on delete restrict,
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict
);

create table public.opportunity_score_snapshots (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  opportunity_id uuid not null,
  score_version text not null,
  total_score numeric(5, 4) not null check (total_score between 0 and 1),
  breakdown jsonb not null,
  input_hash text not null,
  calculated_at timestamptz not null default now(),
  correlation_id uuid not null,
  source public.source_kind not null default 'ares',
  unique (tenant_id, id),
  unique (tenant_id, opportunity_id, score_version, input_hash),
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  check (jsonb_typeof(breakdown) = 'object')
);

create table public.opportunity_state_transitions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  opportunity_id uuid not null,
  from_state text,
  to_state text not null,
  reason text not null,
  evidence_event_id uuid,
  correlation_id uuid not null,
  actor_type public.actor_type not null default 'system',
  actor_id text,
  source public.source_kind not null default 'ares',
  occurred_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  foreign key (tenant_id, evidence_event_id)
    references public.commercial_events(tenant_id, id) on delete restrict,
  check (
    (from_state is null and to_state = 'detected') or
    (from_state = 'detected' and to_state in ('qualifying', 'prioritized', 'closed')) or
    (from_state = 'qualifying' and to_state in ('qualified', 'prioritized', 'closed')) or
    (from_state = 'qualified' and to_state in ('prioritized', 'closed')) or
    (from_state = 'prioritized' and to_state in ('awaiting_decision', 'closed')) or
    (from_state = 'awaiting_decision' and to_state in ('authorized', 'closed')) or
    (from_state = 'authorized' and to_state in ('executing', 'closed')) or
    (from_state = 'executing' and to_state in ('observing', 'closed')) or
    (from_state = 'observing' and to_state = 'closed')
  )
);

alter table public.ares_opportunities
  add column signal_count integer not null default 0 check (signal_count >= 0),
  add column primary_signal_type text,
  add column score_version text,
  add column score_breakdown jsonb not null default '{}'::jsonb,
  add column correlation_id uuid,
  add column last_activity_at timestamptz;

alter table public.deals
  add column external_id text,
  add column owner_user_id uuid references auth.users(id) on delete set null,
  add column last_activity_at timestamptz;

alter table public.context_snapshots
  add column truncated boolean not null default false,
  add column included_event_count integer not null default 0 check (included_event_count >= 0),
  add column omitted_event_count integer not null default 0 check (omitted_event_count >= 0),
  add column correlation_id uuid;

create unique index ares_opportunities_active_deal_type_unique
  on public.ares_opportunities (tenant_id, deal_id, opportunity_type)
  where deal_id is not null and state <> 'closed';
create unique index deals_tenant_external_id_unique
  on public.deals (tenant_id, external_id)
  where external_id is not null;
create unique index context_snapshots_content_unique
  on public.context_snapshots (tenant_id, opportunity_id, content_hash);
create index signals_opportunity_detected_idx
  on public.signals (tenant_id, opportunity_id, detected_at desc);
create index signals_event_idx
  on public.signals (tenant_id, event_id);
create index opportunity_scores_latest_idx
  on public.opportunity_score_snapshots (tenant_id, opportunity_id, calculated_at desc);
create index opportunity_transitions_timeline_idx
  on public.opportunity_state_transitions (tenant_id, opportunity_id, occurred_at desc);
create index ares_opportunities_radar_idx
  on public.ares_opportunities (tenant_id, priority, sla_at, score desc, id)
  where state <> 'closed';
create index commercial_events_aggregate_timeline_idx
  on public.commercial_events (tenant_id, aggregate_type, aggregate_id, occurred_at desc);

alter table public.signals enable row level security;
alter table public.opportunity_score_snapshots enable row level security;
alter table public.opportunity_state_transitions enable row level security;

create policy tenant_read_isolation on public.signals
  for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));
create policy tenant_read_isolation on public.opportunity_score_snapshots
  for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));
create policy tenant_read_isolation on public.opportunity_state_transitions
  for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));

revoke all on public.signals, public.opportunity_score_snapshots,
  public.opportunity_state_transitions from anon, authenticated;
grant select on public.signals, public.opportunity_score_snapshots,
  public.opportunity_state_transitions to authenticated;
