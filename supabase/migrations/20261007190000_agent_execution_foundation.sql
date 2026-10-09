-- Phase 1: server-only orchestration; existing runs/jobs/usage remain authoritative.
create table public.agent_routines (
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  routine_id text not null check (routine_id = 'context-analysis'),
  enabled boolean not null default false,
  version integer not null default 1 check (version > 0),
  updated_by uuid not null references auth.users(id),
  updated_at timestamptz not null default now(),
  primary key (tenant_id, routine_id)
);

create table public.agent_workflows (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id),
  actor_id uuid not null references auth.users(id),
  opportunity_id uuid not null,
  context_ref uuid not null,
  routine_id text not null check (routine_id = 'context-analysis'),
  definition_version text not null,
  definition_hash text not null,
  model_id text not null,
  purpose text not null check (purpose = 'context_analysis'),
  idempotency_key uuid not null,
  request_hash text not null,
  correlation_id uuid not null,
  root_run_id uuid,
  status text not null default 'queued'
    check (status in ('queued','running','succeeded','degraded','failed','blocked','cancelled')),
  max_steps integer not null check (max_steps between 1 and 4),
  max_depth integer not null check (max_depth between 0 and 3),
  budget_limit_usd numeric(12,6) not null check (budget_limit_usd > 0),
  deadline_at timestamptz not null,
  error_code text,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (tenant_id,id),
  unique (tenant_id,actor_id,idempotency_key),
  foreign key (tenant_id,opportunity_id) references public.ares_opportunities(tenant_id,id),
  foreign key (tenant_id,context_ref) references public.context_snapshots(tenant_id,id)
);

alter table public.agent_runs
  add column workflow_id uuid,
  add column parent_run_id uuid,
  add column depth integer check (depth between 0 and 3),
  add column definition_hash text,
  add column input_schema_version text,
  add column checkpoint text check (checkpoint in ('prepared','dispatched','completed')),
  add column lease_token uuid,
  add constraint agent_runs_workflow_fk foreign key (tenant_id,workflow_id)
    references public.agent_workflows(tenant_id,id),
  add constraint agent_runs_parent_fk foreign key (tenant_id,parent_run_id)
    references public.agent_runs(tenant_id,id);

alter table public.agent_workflows add constraint agent_workflow_root_fk
  foreign key (tenant_id,root_run_id) references public.agent_runs(tenant_id,id);

create table public.agent_handoffs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null,
  workflow_id uuid not null,
  from_run_id uuid not null,
  to_job_id uuid not null,
  to_agent text not null,
  schema_version text not null,
  created_at timestamptz not null default now(),
  unique (tenant_id,workflow_id,to_agent),
  foreign key (tenant_id,workflow_id) references public.agent_workflows(tenant_id,id),
  foreign key (tenant_id,from_run_id) references public.agent_runs(tenant_id,id),
  foreign key (tenant_id,to_job_id) references public.jobs(tenant_id,id)
);

-- Opaque fencing token: an expired worker cannot finish a reclaimed job.
alter table public.jobs add column lease_token uuid;
create index agent_workflow_active_idx on public.agent_workflows(tenant_id,status)
  where status in ('queued','running');
create index agent_runs_workflow_idx on public.agent_runs(tenant_id,workflow_id,started_at);
create index jobs_expired_agent_lease_idx on public.jobs(lease_until)
  where kind='agent.execute' and status='running';

alter table public.agent_routines enable row level security;
alter table public.agent_workflows enable row level security;
alter table public.agent_handoffs enable row level security;
-- No browser grants: HTTP handlers revalidate tenant, membership and portfolio.
revoke all on public.agent_routines,public.agent_workflows,public.agent_handoffs
  from public,anon,authenticated;
