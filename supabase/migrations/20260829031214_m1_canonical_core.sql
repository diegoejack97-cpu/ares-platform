create extension if not exists pgcrypto with schema extensions;

create type public.membership_role as enum ('admin', 'manager', 'seller', 'auditor');
create type public.actor_type as enum ('human', 'ares_agent', 'system', 'external_system');
create type public.source_kind as enum ('crm', 'ares', 'human', 'channel', 'reconciliation');
create type public.job_status as enum ('queued', 'running', 'succeeded', 'failed', 'dead_letter');
create type public.intervention_status as enum ('open', 'deciding', 'executing', 'observing', 'closed', 'cancelled');
create type public.attribution_level as enum ('observed', 'associated', 'influenced', 'incremental_proven');

create table public.tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  timezone text not null default 'America/Sao_Paulo',
  locale text not null default 'pt-BR',
  status text not null default 'active' check (status in ('active', 'suspended', 'archived')),
  retention_policy jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1 check (version > 0)
);

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete restrict,
  display_name text not null,
  status text not null default 'active' check (status in ('active', 'disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.teams (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  parent_team_id uuid,
  name text not null,
  manager_user_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, name),
  foreign key (tenant_id, parent_team_id)
    references public.teams(tenant_id, id) on delete restrict
);

create table public.memberships (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  role public.membership_role not null,
  team_id uuid,
  scopes text[] not null default '{}'::text[],
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, user_id),
  foreign key (tenant_id, team_id)
    references public.teams(tenant_id, id) on delete restrict
);

create table public.connections (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  provider text not null,
  status text not null default 'configured' check (status in ('configured', 'healthy', 'degraded', 'revoked')),
  auth_type text not null default 'shared_secret',
  encrypted_secret_ref text,
  capabilities jsonb not null default '{}'::jsonb,
  last_sync_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, provider)
);

create table public.webhook_receipts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  connection_id uuid not null,
  provider_event_id text,
  payload_hash text not null,
  headers_redacted jsonb not null default '{}'::jsonb,
  raw_payload_ref text not null,
  status text not null default 'received' check (status in ('received', 'queued', 'processed', 'rejected', 'failed')),
  error_code text,
  correlation_id uuid not null,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  unique (tenant_id, id),
  foreign key (tenant_id, connection_id)
    references public.connections(tenant_id, id) on delete restrict
);

create unique index webhook_receipts_provider_event_unique
  on public.webhook_receipts (tenant_id, connection_id, provider_event_id)
  where provider_event_id is not null;

create table public.commercial_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  event_type text not null,
  event_version integer not null default 1 check (event_version > 0),
  producer text not null,
  aggregate_type text not null,
  aggregate_id text not null,
  provider_event_id text,
  correlation_id uuid not null,
  causation_id uuid,
  intervention_id uuid,
  actor_type public.actor_type not null default 'external_system',
  actor_id text,
  source public.source_kind not null,
  source_ref text,
  occurred_at timestamptz not null,
  recorded_at timestamptz not null default now(),
  data jsonb not null default '{}'::jsonb,
  payload_hash text not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create unique index commercial_events_provider_event_unique
  on public.commercial_events (tenant_id, producer, provider_event_id)
  where provider_event_id is not null;
create index commercial_events_tenant_recorded_idx
  on public.commercial_events (tenant_id, recorded_at desc);
create index commercial_events_correlation_idx
  on public.commercial_events (tenant_id, correlation_id);

create table public.inbox_receipts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  consumer text not null,
  event_id uuid not null,
  processed_at timestamptz not null default now(),
  result_hash text,
  unique (tenant_id, consumer, event_id),
  foreign key (tenant_id, event_id)
    references public.commercial_events(tenant_id, id) on delete restrict
);

create table public.outbox_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  aggregate_type text not null,
  aggregate_id text not null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  status public.job_status not null default 'queued',
  attempts integer not null default 0 check (attempts >= 0),
  available_at timestamptz not null default now(),
  correlation_id uuid not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  kind text not null,
  payload_version integer not null default 1 check (payload_version > 0),
  payload jsonb not null default '{}'::jsonb,
  status public.job_status not null default 'queued',
  attempts integer not null default 0 check (attempts >= 0),
  run_after timestamptz not null default now(),
  lease_owner text,
  lease_until timestamptz,
  error_code text,
  correlation_id uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create index jobs_claim_idx
  on public.jobs (run_after, created_at)
  where status = 'queued';

create table public.event_failures (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  event_id uuid,
  job_id uuid,
  category text not null,
  redacted_detail text,
  replay_status text not null default 'pending' check (replay_status in ('pending', 'replayed', 'discarded')),
  correlation_id uuid not null,
  created_at timestamptz not null default now(),
  check (event_id is not null or job_id is not null),
  foreign key (tenant_id, event_id)
    references public.commercial_events(tenant_id, id) on delete restrict,
  foreign key (tenant_id, job_id)
    references public.jobs(tenant_id, id) on delete restrict
);

create table public.subjects (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  subject_type text not null check (subject_type in ('person', 'company')),
  display_name text not null,
  source_authority text not null check (source_authority in ('external', 'native')),
  external_ref jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1 check (version > 0),
  unique (tenant_id, id)
);

create table public.deals (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  subject_id uuid,
  title text not null,
  external_stage text,
  status text not null default 'open' check (status in ('open', 'won', 'lost')),
  value numeric(18, 2) check (value is null or value >= 0),
  currency char(3) check (currency is null or currency ~ '^[A-Z]{3}$'),
  source_authority text not null default 'external' check (source_authority in ('external', 'native')),
  external_ref jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1 check (version > 0),
  unique (tenant_id, id),
  foreign key (tenant_id, subject_id)
    references public.subjects(tenant_id, id) on delete restrict
);

create table public.ares_opportunities (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  deal_id uuid,
  opportunity_type text not null,
  state text not null check (state in ('detected', 'qualifying', 'qualified', 'prioritized', 'awaiting_decision', 'authorized', 'executing', 'observing', 'closed')),
  score numeric(5, 4) not null default 0 check (score between 0 and 1),
  priority smallint not null default 3 check (priority between 0 and 3),
  owner_user_id uuid references auth.users(id) on delete set null,
  sla_at timestamptz,
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version integer not null default 1 check (version > 0),
  unique (tenant_id, id),
  foreign key (tenant_id, deal_id)
    references public.deals(tenant_id, id) on delete restrict
);

create table public.context_snapshots (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  opportunity_id uuid not null,
  snapshot_version integer not null check (snapshot_version > 0),
  opportunity_state text not null,
  facts_json jsonb not null default '{}'::jsonb,
  citations_json jsonb not null default '[]'::jsonb,
  token_estimate integer not null default 0 check (token_estimate >= 0),
  content_hash text not null,
  source public.source_kind not null,
  source_ref text,
  captured_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, opportunity_id, snapshot_version),
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict
);

create table public.ares_interventions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  opportunity_id uuid not null,
  correlation_id uuid not null,
  state_before_ref uuid not null,
  state_after_ref uuid,
  ares_intervention boolean not null default true,
  status public.intervention_status not null default 'open',
  source public.source_kind not null,
  source_ref text,
  created_at timestamptz not null default now(),
  closed_at timestamptz,
  unique (tenant_id, id),
  unique (tenant_id, correlation_id),
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  foreign key (tenant_id, state_before_ref)
    references public.context_snapshots(tenant_id, id) on delete restrict,
  foreign key (tenant_id, state_after_ref)
    references public.context_snapshots(tenant_id, id) on delete restrict,
  check ((status <> 'closed') or (closed_at is not null and state_after_ref is not null))
);

alter table public.commercial_events
  add constraint commercial_events_intervention_fk
  foreign key (tenant_id, intervention_id)
  references public.ares_interventions(tenant_id, id) on delete restrict;

create table public.policy_decisions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  policy_set text not null,
  policy_version integer not null check (policy_version > 0),
  inputs_hash text not null,
  verdict text not null check (verdict in ('allow', 'require_approval', 'deny')),
  rules_matched jsonb not null default '[]'::jsonb,
  obligations jsonb not null default '[]'::jsonb,
  expires_at timestamptz,
  decided_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create table public.recommendations (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  opportunity_id uuid not null,
  correlation_id uuid not null,
  kind text not null,
  recommended_action jsonb not null,
  rationale text not null,
  confidence numeric(5, 4) not null check (confidence between 0 and 1),
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'expired', 'superseded')),
  source public.source_kind not null default 'ares',
  source_ref text,
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  unique (tenant_id, id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  check (expires_at is null or expires_at > created_at)
);

create table public.decisions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  recommendation_id uuid not null,
  policy_decision_id uuid not null,
  correlation_id uuid not null,
  actor_type public.actor_type not null,
  actor_id text,
  verdict text not null check (verdict in ('approved', 'rejected', 'edited')),
  reason text,
  source public.source_kind not null,
  source_ref text,
  decided_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, recommendation_id)
    references public.recommendations(tenant_id, id) on delete restrict,
  foreign key (tenant_id, policy_decision_id)
    references public.policy_decisions(tenant_id, id) on delete restrict
);

create table public.action_executions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  correlation_id uuid not null,
  executed_action jsonb not null,
  target jsonb not null,
  actor_type public.actor_type not null,
  actor_id text,
  source public.source_kind not null,
  source_ref text,
  status text not null check (status in ('requested', 'running', 'succeeded', 'failed', 'cancelled')),
  idempotency_key text not null,
  attempts integer not null default 0 check (attempts >= 0),
  started_at timestamptz,
  finished_at timestamptz,
  result jsonb,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, idempotency_key),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict
);

create table public.outcomes (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  opportunity_id uuid not null,
  action_execution_id uuid,
  correlation_id uuid not null,
  state_after_ref uuid not null,
  result_type text not null,
  sale_value numeric(18, 2),
  ares_influenced_value numeric(18, 2),
  incremental_value numeric(18, 2),
  currency char(3),
  attribution_level public.attribution_level not null default 'observed',
  attribution_method text,
  actor_type public.actor_type not null,
  actor_id text,
  source public.source_kind not null,
  source_ref text,
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  foreign key (tenant_id, action_execution_id)
    references public.action_executions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, state_after_ref)
    references public.context_snapshots(tenant_id, id) on delete restrict,
  check (sale_value is null or sale_value >= 0),
  check (ares_influenced_value is null or ares_influenced_value >= 0),
  check (incremental_value is null or incremental_value >= 0),
  check (currency is null or currency ~ '^[A-Z]{3}$'),
  check (incremental_value is null or attribution_level = 'incremental_proven'),
  check (ares_influenced_value is null or attribution_level in ('influenced', 'incremental_proven')),
  check (attribution_level <> 'incremental_proven' or attribution_method is not null)
);

create or replace function public.current_tenant_id()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'active_tenant_id', '')::uuid
$$;

create or replace function public.can_access_tenant(target_tenant_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select
    target_tenant_id = public.current_tenant_id()
    and exists (
      select 1
      from public.memberships membership
      where membership.tenant_id = target_tenant_id
        and membership.user_id = auth.uid()
        and membership.active
    )
$$;

revoke all on function public.current_tenant_id() from public;
revoke all on function public.can_access_tenant(uuid) from public;
grant execute on function public.current_tenant_id() to authenticated;
grant execute on function public.can_access_tenant(uuid) to authenticated;

alter table public.tenants enable row level security;
alter table public.profiles enable row level security;

create policy tenants_read_active_membership
  on public.tenants for select to authenticated
  using ((select public.can_access_tenant(id)));

create policy profiles_read_self
  on public.profiles for select to authenticated
  using ((select auth.uid()) = user_id);

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'teams', 'memberships', 'connections', 'webhook_receipts',
    'commercial_events', 'inbox_receipts', 'outbox_events', 'jobs',
    'event_failures', 'subjects', 'deals', 'ares_opportunities',
    'context_snapshots', 'ares_interventions', 'policy_decisions',
    'recommendations', 'decisions', 'action_executions', 'outcomes'
  ]
  loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format(
      'create policy tenant_read_isolation on public.%I for select to authenticated using ((select public.can_access_tenant(tenant_id)))',
      table_name
    );
  end loop;
end
$$;

revoke all on all tables in schema public from anon, authenticated;
grant select on table
  public.tenants,
  public.profiles,
  public.teams,
  public.memberships,
  public.connections,
  public.webhook_receipts,
  public.commercial_events,
  public.jobs,
  public.ares_opportunities,
  public.context_snapshots,
  public.ares_interventions,
  public.policy_decisions,
  public.recommendations,
  public.decisions,
  public.action_executions,
  public.outcomes
to authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'webhook-raw',
  'webhook-raw',
  false,
  1048576,
  array['application/json']::text[]
)
on conflict (id) do nothing;
