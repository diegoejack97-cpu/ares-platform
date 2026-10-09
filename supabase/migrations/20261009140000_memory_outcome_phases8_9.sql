-- Tenant-private knowledge; content is not available to browser database roles.
create extension if not exists vector with schema extensions;
create table public.knowledge_settings (
 tenant_id uuid primary key references public.tenants(id), version integer not null default 0,
 enabled boolean not null default false, external_consent boolean not null default false,
 outcomes_enabled boolean not null default false, episodes_enabled boolean not null default false,
 observation_hours integer not null default 48 check(observation_hours between 1 and 720),
 retention_days integer not null default 90 check(retention_days between 1 and 365),
 updated_by uuid not null, updated_at timestamptz not null default now()
);
alter table public.tenant_quotas add column memory_storage_bytes bigint not null default 20971520 check(memory_storage_bytes >= 0);
alter table public.tenant_quotas add column embedding_daily_budget_brl numeric(18,6) not null default 1 check(embedding_daily_budget_brl >= 0);
create table public.knowledge_documents (
 id uuid primary key, tenant_id uuid not null references public.tenants(id),
 title text not null, source_label text not null, classification text not null check(classification in ('internal','restricted')),
 allowed_roles text[] not null, owner_user_id uuid, purposes text[] not null,
 current_version integer not null default 1, deleted boolean not null default false,
 created_by uuid not null, created_at timestamptz not null default now(), unique(tenant_id,id)
);
create table public.knowledge_versions (
 id uuid primary key, tenant_id uuid not null, document_id uuid not null,
 version integer not null, content_hash text not null, original_text text,
 size_bytes integer not null, expires_at timestamptz not null,
 status text not null check(status in ('queued','indexing','ready','lexical_only','failed','superseded','deleted')),
 error_code text, run_id uuid, created_at timestamptz not null default now(),
 unique(tenant_id,id), unique(tenant_id,document_id,version),
 foreign key(tenant_id,document_id) references public.knowledge_documents(tenant_id,id)
);
create table public.knowledge_chunks (
 id uuid primary key, tenant_id uuid not null, version_id uuid not null,
 ordinal integer not null, content text not null, content_hash text not null,
 search_vector tsvector generated always as (to_tsvector('portuguese', content)) stored,
 embedding extensions.vector(1536), embedding_model text, embedding_version text,
 unique(tenant_id,version_id,ordinal),
 foreign key(tenant_id,version_id) references public.knowledge_versions(tenant_id,id)
);
create index knowledge_chunks_fts on public.knowledge_chunks using gin(search_vector);
create index knowledge_chunks_scope on public.knowledge_chunks(tenant_id,version_id);
create table public.knowledge_audit (
 id uuid primary key, tenant_id uuid not null references public.tenants(id), actor_id uuid not null,
 document_id uuid, operation text not null, reason text not null,
 metadata jsonb not null default '{}', created_at timestamptz not null default now()
);
create table public.knowledge_reads (
 id uuid primary key, tenant_id uuid not null references public.tenants(id), actor_id uuid not null,
 purpose text not null, references_json jsonb not null, content_hash text not null,
 created_at timestamptz not null default now(), valid_until timestamptz not null
);
create table public.knowledge_embedding_budget (
 tenant_id uuid not null references public.tenants(id), run_id uuid primary key,
 reserved_usd numeric(18,8) not null, measured_usd numeric(18,8),
 created_at timestamptz not null default now()
);
create table public.outcome_evaluations (
 id uuid primary key, tenant_id uuid not null, intervention_id uuid not null,
 actor_id uuid not null, context_hash text not null, facts_json jsonb not null,
 status text not null check(status in ('queued','running','ready','degraded','pending','failed')),
 explanation_json jsonb, run_id uuid, error_code text,
 created_at timestamptz not null default now(), finished_at timestamptz,
 unique(tenant_id,id), unique(tenant_id,intervention_id,context_hash),
 foreign key(tenant_id,intervention_id) references public.ares_interventions(tenant_id,id)
);
create table public.outcome_feedback (
 id uuid primary key, tenant_id uuid not null, evaluation_id uuid not null, actor_id uuid not null,
 rating text not null check(rating in ('helpful','unhelpful')), rationale text not null,
 created_at timestamptz not null default now(),
 foreign key(tenant_id,evaluation_id) references public.outcome_evaluations(tenant_id,id)
);
do $$ declare n text; begin
 foreach n in array array['knowledge_settings','knowledge_documents','knowledge_versions','knowledge_chunks','knowledge_audit','knowledge_reads','knowledge_embedding_budget','outcome_evaluations','outcome_feedback'] loop
  execute format('alter table public.%I enable row level security',n);
  execute format('revoke all on public.%I from public, anon, authenticated',n);
 end loop;
end $$;
alter table public.agent_runs drop constraint agent_runs_commercial_context_required;
alter table public.agent_runs add constraint agent_runs_commercial_context_required check (
 agent_name='chat' or (agent_name in ('portfolio-prioritizer','commercial-analyst','memory-indexer') and context_ref is not null)
 or (opportunity_id is not null and (context_ref is not null or (agent_name='sentinel-interpreter' and sentinel_context_ref is not null)))
);
