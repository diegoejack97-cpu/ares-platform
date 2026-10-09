alter table public.outcome_evaluations add column checked_at timestamptz not null default now();
create index outcome_evaluation_scan on public.outcome_evaluations(tenant_id,intervention_id,checked_at);
