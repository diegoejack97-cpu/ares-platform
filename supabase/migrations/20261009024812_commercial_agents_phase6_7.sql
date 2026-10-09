-- Phase 6/7 server-only control plane; opt-in, no browser data grants.
create table public.commercial_routines (
 tenant_id uuid primary key references public.tenants(id),
 enabled boolean not null default false,
 recommendations_enabled boolean not null default false,
 proactive_enabled boolean not null default false,
 version integer not null default 1 check(version>0),
 criterion text not null check(criterion in ('urgency','value','deadline','attractiveness')),
 currency text check(currency ~ '^[A-Z]{3}$'),
 calendar_json jsonb not null,
 cooldown_hours integer not null check(cooldown_hours between 1 and 168),
 daily_proposal_limit integer not null check(daily_proposal_limit between 1 and 20),
 updated_by uuid not null references auth.users(id),
 updated_at timestamptz not null default now(),
 next_run_at timestamptz,
 check(criterion<>'value' or currency is not null),
 check(not proactive_enabled or recommendations_enabled)
);
create table public.portfolio_analyses (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references public.tenants(id),
 actor_id uuid not null references auth.users(id), criterion text not null,
 currency text, request_hash text not null, relevant_hash text not null,
 context_ref uuid not null, config_version integer not null,
 actor_role text not null, correlation_id uuid not null,
 status text not null default 'queued' check(status in ('queued','running','ready','degraded','failed','blocked')),
 stage integer not null default 0 check(stage between 0 and 2),
 ranking_json jsonb, briefing_json jsonb, error_code text,
 created_at timestamptz not null default now(), valid_until timestamptz not null,
 unique(tenant_id,id),
 foreign key(tenant_id,context_ref) references public.context_snapshots(tenant_id,id)
);
create index portfolio_actor_scope on public.portfolio_analyses(tenant_id,actor_id,request_hash,created_at desc);
create table public.commercial_proposals (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
 opportunity_id uuid not null, actor_id uuid not null references auth.users(id),
 context_hash text not null, trigger_kind text not null check(trigger_kind in ('finding','portfolio')),
 status text not null default 'queued' check(status in ('queued','running','finished','failed','blocked')),
 recommendation_id uuid, created_at timestamptz not null default now(), error_code text,
 unique(tenant_id,opportunity_id,context_hash),
 foreign key(tenant_id,opportunity_id) references public.ares_opportunities(tenant_id,id),
 foreign key(tenant_id,recommendation_id) references public.recommendations(tenant_id,id)
);
create table public.recommendation_context_guards (
 tenant_id uuid not null, recommendation_id uuid not null, opportunity_id uuid not null,
 relevant_hash text not null, expected_version integer not null,
 valid_until timestamptz not null, plan_json jsonb not null,
 primary key(tenant_id,recommendation_id),
 foreign key(tenant_id,recommendation_id) references public.recommendations(tenant_id,id),
 foreign key(tenant_id,opportunity_id) references public.ares_opportunities(tenant_id,id)
);
alter table public.agent_runs drop constraint agent_runs_commercial_context_required;
alter table public.agent_runs add constraint agent_runs_commercial_context_required check (
 agent_name='chat' or
 (agent_name in ('portfolio-prioritizer','commercial-analyst') and context_ref is not null) or
 (opportunity_id is not null and (context_ref is not null or
 (agent_name='sentinel-interpreter' and sentinel_context_ref is not null)))
);
alter table public.commercial_routines enable row level security;
alter table public.portfolio_analyses enable row level security;
alter table public.commercial_proposals enable row level security;
alter table public.recommendation_context_guards enable row level security;
revoke all on public.commercial_routines,public.portfolio_analyses,public.commercial_proposals,
 public.recommendation_context_guards from public,anon,authenticated;
