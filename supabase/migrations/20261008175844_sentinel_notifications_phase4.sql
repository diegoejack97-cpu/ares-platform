-- Typed schedules, auditable finding revisions and personal notification state.
alter table public.sentinel_schedules
  add column criteria_json jsonb not null default '{}'::jsonb,
  add column calendar_json jsonb not null default '{}'::jsonb,
  add column interpret_with_ai boolean not null default false,
  add column last_error_code text,
  add column last_matched_count integer;
alter table public.sentinel_findings
  add column status text not null default 'open' check(status in ('open','updated','resolved','superseded')),
  add column revision integer not null default 1 check(revision>0),
  add column condition_hash text,
  add column updated_at timestamptz not null default now(),
  add column resolved_at timestamptz,
  add column severity text not null default 'normal' check(severity in ('low','normal','high','critical')),
  add column summary text,
  add column interpretation_status text not null default 'not_requested'
    check(interpretation_status in ('not_requested','pending','running','ready','degraded','failed','superseded')),
  add column interpretation_json jsonb,
  add column interpretation_run_id uuid;
create index sentinel_inbox_order on public.sentinel_findings(tenant_id,updated_at desc,id);
create table public.sentinel_finding_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null,
  finding_id uuid not null,
  revision integer not null,
  status text not null,
  snapshot_json jsonb not null,
  content_hash text not null,
  occurred_at timestamptz not null default now(),
  unique(tenant_id,finding_id,revision),
  foreign key(tenant_id,finding_id) references public.sentinel_findings(tenant_id,id) on delete cascade
);
alter table public.sentinel_finding_events enable row level security;
revoke all on public.sentinel_finding_events from public,anon,authenticated;
create table public.sentinel_notification_state (
  tenant_id uuid not null,
  finding_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  read_revision integer not null default 0,
  archived_revision integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key(tenant_id,finding_id,user_id),
  foreign key(tenant_id,finding_id) references public.sentinel_findings(tenant_id,id) on delete cascade
);
alter table public.sentinel_notification_state enable row level security;
revoke all on public.sentinel_notification_state from public,anon,authenticated;

-- Keep commercial runs bound to a real, tenant-scoped closed snapshot.
alter table public.sentinel_finding_events add constraint sentinel_event_tenant_id unique(tenant_id,id);
alter table public.agent_runs add column sentinel_context_ref uuid;
alter table public.agent_runs add constraint agent_runs_sentinel_context foreign key(tenant_id,sentinel_context_ref) references public.sentinel_finding_events(tenant_id,id);
alter table public.agent_runs drop constraint agent_runs_commercial_context_required;
alter table public.agent_runs add constraint agent_runs_commercial_context_required
  check(agent_name='chat' or (opportunity_id is not null and
    (context_ref is not null or (agent_name='sentinel-interpreter' and sentinel_context_ref is not null))));
