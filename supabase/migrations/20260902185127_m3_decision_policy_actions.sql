alter table public.recommendations
  add column context_ref uuid,
  add column run_id uuid,
  add column alternatives jsonb not null default '[]'::jsonb,
  add column contraindication text,
  add column output_schema_version text not null default 'recommendation.v1',
  add column urgency text not null default 'normal'
    check (urgency in ('low', 'normal', 'high', 'critical')),
  add column generation_mode text not null default 'deterministic_fallback'
    check (generation_mode in ('agno_openai', 'deterministic_fallback')),
  add column version integer not null default 1 check (version > 0),
  add column updated_at timestamptz not null default now();

alter table public.recommendations
  add constraint recommendations_context_ref_fk
  foreign key (tenant_id, context_ref)
  references public.context_snapshots(tenant_id, id) on delete restrict;

alter table public.decisions
  add column edited_payload jsonb,
  add column expected_version integer not null default 1 check (expected_version > 0);

create unique index decisions_one_final_per_recommendation
  on public.decisions (tenant_id, recommendation_id);

create table public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  opportunity_id uuid not null,
  context_ref uuid not null,
  correlation_id uuid not null,
  agent_name text not null,
  agent_version text not null,
  model_id text,
  prompt_hash text not null,
  output_schema_version text not null,
  generation_mode text not null
    check (generation_mode in ('agno_openai', 'deterministic_fallback')),
  status text not null check (status in ('running', 'succeeded', 'failed', 'degraded')),
  output_json jsonb,
  error_code text,
  input_tokens integer not null default 0 check (input_tokens >= 0),
  output_tokens integer not null default 0 check (output_tokens >= 0),
  cost_usd numeric(12, 6) not null default 0 check (cost_usd >= 0),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (tenant_id, id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  foreign key (tenant_id, context_ref)
    references public.context_snapshots(tenant_id, id) on delete restrict
);

alter table public.recommendations
  add constraint recommendations_run_id_fk
  foreign key (tenant_id, run_id)
  references public.agent_runs(tenant_id, id) on delete restrict;

alter table public.policy_decisions
  add column intervention_id uuid,
  add column recommendation_id uuid,
  add column action_kind text,
  add column policy_hash text,
  add column source public.source_kind not null default 'ares',
  add column source_ref text;

alter table public.policy_decisions
  add constraint policy_decisions_intervention_fk
  foreign key (tenant_id, intervention_id)
  references public.ares_interventions(tenant_id, id) on delete restrict,
  add constraint policy_decisions_recommendation_fk
  foreign key (tenant_id, recommendation_id)
  references public.recommendations(tenant_id, id) on delete restrict;

create table public.approval_requests (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  recommendation_id uuid not null,
  policy_decision_id uuid not null,
  opportunity_id uuid not null,
  correlation_id uuid not null,
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'edited', 'rejected', 'expired', 'superseded')),
  required_role public.membership_role not null default 'manager',
  version integer not null default 1 check (version > 0),
  expires_at timestamptz not null,
  resolved_at timestamptz,
  resolved_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, recommendation_id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, recommendation_id)
    references public.recommendations(tenant_id, id) on delete restrict,
  foreign key (tenant_id, policy_decision_id)
    references public.policy_decisions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict,
  check ((status = 'pending' and resolved_at is null) or status <> 'pending')
);

create table public.action_intents (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intervention_id uuid not null,
  recommendation_id uuid not null,
  decision_id uuid not null,
  policy_decision_id uuid not null,
  context_ref uuid not null,
  correlation_id uuid not null,
  action_kind text not null check (action_kind in ('create_task', 'add_note', 'update_stage')),
  action_payload jsonb not null,
  idempotency_key text not null,
  status text not null default 'authorized'
    check (status in ('authorized', 'executing', 'succeeded', 'failed', 'cancelled')),
  actor_type public.actor_type not null,
  actor_id text,
  source public.source_kind not null,
  source_ref text,
  authorized_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, idempotency_key),
  unique (tenant_id, decision_id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, recommendation_id)
    references public.recommendations(tenant_id, id) on delete restrict,
  foreign key (tenant_id, decision_id)
    references public.decisions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, policy_decision_id)
    references public.policy_decisions(tenant_id, id) on delete restrict,
  foreign key (tenant_id, context_ref)
    references public.context_snapshots(tenant_id, id) on delete restrict,
  check (jsonb_typeof(action_payload) = 'object')
);

create table public.action_attempts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  intent_id uuid not null,
  intervention_id uuid not null,
  correlation_id uuid not null,
  attempt_no integer not null check (attempt_no > 0),
  status text not null check (status in ('running', 'succeeded', 'failed')),
  external_request jsonb not null default '{}'::jsonb,
  external_response jsonb,
  error_code text,
  actor_type public.actor_type not null default 'system',
  actor_id text,
  source public.source_kind not null default 'ares',
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (tenant_id, id),
  unique (tenant_id, intent_id, attempt_no),
  foreign key (tenant_id, intent_id)
    references public.action_intents(tenant_id, id) on delete restrict,
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict
);

alter table public.action_executions
  add column intent_id uuid,
  add column attempt_id uuid,
  add column recommendation_id uuid,
  add column decision_id uuid;

alter table public.action_executions
  add constraint action_executions_intent_fk
  foreign key (tenant_id, intent_id)
  references public.action_intents(tenant_id, id) on delete restrict,
  add constraint action_executions_attempt_fk
  foreign key (tenant_id, attempt_id)
  references public.action_attempts(tenant_id, id) on delete restrict,
  add constraint action_executions_recommendation_fk
  foreign key (tenant_id, recommendation_id)
  references public.recommendations(tenant_id, id) on delete restrict,
  add constraint action_executions_decision_fk
  foreign key (tenant_id, decision_id)
  references public.decisions(tenant_id, id) on delete restrict;

create unique index action_executions_one_per_intent
  on public.action_executions (tenant_id, intent_id)
  where intent_id is not null;
create index agent_runs_opportunity_idx
  on public.agent_runs (tenant_id, opportunity_id, started_at desc);
create index approvals_pending_idx
  on public.approval_requests (tenant_id, expires_at, created_at)
  where status = 'pending';
create index action_intents_status_idx
  on public.action_intents (tenant_id, status, authorized_at);
create index action_attempts_intent_idx
  on public.action_attempts (tenant_id, intent_id, attempt_no desc);
create index policy_decisions_recommendation_idx
  on public.policy_decisions (tenant_id, recommendation_id);

alter table public.agent_runs enable row level security;
alter table public.approval_requests enable row level security;
alter table public.action_intents enable row level security;
alter table public.action_attempts enable row level security;

create policy tenant_read_isolation on public.agent_runs
  for select to authenticated using ((select private.has_tenant_role(tenant_id)));
create policy tenant_read_isolation on public.approval_requests
  for select to authenticated using ((select private.has_tenant_role(tenant_id)));
create policy tenant_read_isolation on public.action_intents
  for select to authenticated using ((select private.has_tenant_role(tenant_id)));
create policy tenant_read_isolation on public.action_attempts
  for select to authenticated using ((select private.has_tenant_role(tenant_id)));

revoke all on public.agent_runs, public.approval_requests,
  public.action_intents, public.action_attempts from anon, authenticated;
grant select on public.agent_runs, public.approval_requests,
  public.action_intents, public.action_attempts to authenticated;
