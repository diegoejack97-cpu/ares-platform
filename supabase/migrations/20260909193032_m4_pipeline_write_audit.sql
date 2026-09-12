create table public.external_write_dedup (
  id uuid primary key, tenant_id uuid not null, connection_id uuid not null, deal_id uuid not null,
  idempotency_key uuid not null, fingerprint text not null, actor_id uuid not null,
  actor_type text not null default 'human', correlation_id uuid not null,
  policy_decision_id uuid not null, source text not null default 'ares:pipeline',
  ares_intervention boolean not null default false check (ares_intervention = false),
  status text not null check(status in ('pending','succeeded','conflict','failed','uncertain')),
  request_json jsonb not null, state_before jsonb not null, state_after jsonb,
  response_json jsonb, error_code text, created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(), unique(tenant_id,id),
  unique(tenant_id,idempotency_key),
  foreign key(tenant_id,connection_id) references public.connections(tenant_id,id),
  foreign key(tenant_id,deal_id) references public.deals(tenant_id,id),
  foreign key(tenant_id,policy_decision_id) references public.policy_decisions(tenant_id,id)
);
create index external_write_deal_idx on public.external_write_dedup(tenant_id,deal_id);
create index external_write_connection_idx on public.external_write_dedup(tenant_id,connection_id);
create index external_write_policy_idx on public.external_write_dedup(tenant_id,policy_decision_id);
create table public.deal_stage_history (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null, deal_id uuid not null,
  write_id uuid not null, from_stage text not null, to_stage text not null,
  actor_type text not null default 'human', actor_id uuid not null,
  correlation_id uuid not null, source text not null default 'crm',
  occurred_at timestamptz not null default now(), unique(tenant_id,write_id),
  foreign key(tenant_id,deal_id) references public.deals(tenant_id,id),
  foreign key(tenant_id,write_id) references public.external_write_dedup(tenant_id,id)
);
create index deal_stage_history_deal_idx on public.deal_stage_history(tenant_id,deal_id,occurred_at);
create table public.audit_log (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references public.tenants(id),
  actor_type text not null, actor_id uuid not null, action text not null,
  correlation_id uuid not null, source text not null, data jsonb not null,
  occurred_at timestamptz not null default now()
);
create index audit_log_tenant_time_idx on public.audit_log(tenant_id,occurred_at);
do $$ declare tab text; begin
  foreach tab in array array['external_write_dedup','deal_stage_history','audit_log'] loop
    execute format('alter table public.%I enable row level security',tab);
    execute format('create policy tenant_read_isolation on public.%I for select to authenticated
      using ((select private.has_tenant_role(tenant_id)))',tab);
    execute format('revoke all on public.%I from anon,authenticated',tab);
    execute format('grant select on public.%I to authenticated',tab);
  end loop;
end $$;
do $$ declare tab text; begin
  foreach tab in array array['external_write_dedup','deal_stage_history','audit_log'] loop
    execute format('create policy active_connect_entitlement on public.%I as restrictive
      for select to authenticated using (exists(select 1 from public.tenant_entitlements e
      where e.tenant_id=%I.tenant_id and e.module=''ares_connect'' and e.status=''active''
      and (e.expires_at is null or e.expires_at>now())))',tab,tab);
  end loop;
end $$;
