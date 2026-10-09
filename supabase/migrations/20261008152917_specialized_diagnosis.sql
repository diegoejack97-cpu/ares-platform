-- Opt-in replacement inside the existing routine; no extra invisible agent slot.
alter table public.agent_routines add column specialists_enabled boolean not null default false;
alter table public.agent_workflows
  add column source_fingerprint text,
  add column source_content_hash text,
  add column source_content_json jsonb,
  add column analysis_valid_until timestamptz;
create index specialized_analysis_lookup on public.agent_workflows
  (tenant_id,actor_id,opportunity_id,created_at desc)
  where definition_version='opportunity-analysis.v1';

-- Persist receipts even when a new request reuses a still-current analysis.
create table public.agent_analysis_requests (
  tenant_id uuid not null,
  actor_id uuid not null references auth.users(id),
  idempotency_key uuid not null,
  request_hash text not null,
  workflow_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id,actor_id,idempotency_key),
  foreign key (tenant_id,workflow_id) references public.agent_workflows(tenant_id,id) on delete cascade
);
alter table public.agent_analysis_requests enable row level security;
revoke all on public.agent_analysis_requests from public,anon,authenticated;
