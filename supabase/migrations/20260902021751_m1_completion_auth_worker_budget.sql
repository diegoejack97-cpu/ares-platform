create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create or replace function private.has_tenant_role(
  target_tenant_id uuid,
  allowed_roles public.membership_role[] default null
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select
    target_tenant_id = nullif(
      auth.jwt() -> 'app_metadata' ->> 'active_tenant_id',
      ''
    )::uuid
    and exists (
      select 1
      from public.memberships membership
      where membership.tenant_id = target_tenant_id
        and membership.user_id = (select auth.uid())
        and membership.active
        and (allowed_roles is null or membership.role = any(allowed_roles))
    )
$$;

revoke all on function private.has_tenant_role(uuid, public.membership_role[]) from public;
grant execute on function private.has_tenant_role(uuid, public.membership_role[])
  to authenticated;

drop policy if exists tenants_read_active_membership on public.tenants;
create policy tenants_read_active_membership
  on public.tenants for select to authenticated
  using ((select private.has_tenant_role(id)));

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
    execute format('drop policy if exists tenant_read_isolation on public.%I', table_name);
    execute format(
      'create policy tenant_read_isolation on public.%I for select to authenticated using ((select private.has_tenant_role(tenant_id)))',
      table_name
    );
  end loop;
end
$$;

drop function if exists public.can_access_tenant(uuid);

create policy teams_manager_insert
  on public.teams for insert to authenticated
  with check ((select private.has_tenant_role(
    tenant_id,
    array['admin', 'manager']::public.membership_role[]
  )));

create policy teams_manager_update
  on public.teams for update to authenticated
  using ((select private.has_tenant_role(
    tenant_id,
    array['admin', 'manager']::public.membership_role[]
  )))
  with check ((select private.has_tenant_role(
    tenant_id,
    array['admin', 'manager']::public.membership_role[]
  )));

create policy memberships_admin_insert
  on public.memberships for insert to authenticated
  with check ((select private.has_tenant_role(
    tenant_id,
    array['admin']::public.membership_role[]
  )));

create policy memberships_admin_update
  on public.memberships for update to authenticated
  using ((select private.has_tenant_role(
    tenant_id,
    array['admin']::public.membership_role[]
  )))
  with check ((select private.has_tenant_role(
    tenant_id,
    array['admin']::public.membership_role[]
  )));

grant insert, update on public.teams, public.memberships to authenticated;

create table public.ai_budget_limits (
  tenant_id uuid primary key references public.tenants(id) on delete restrict,
  daily_limit_usd numeric(12, 6) not null check (daily_limit_usd > 0),
  monthly_limit_usd numeric(12, 6) not null check (monthly_limit_usd > 0),
  warning_percent smallint not null default 80 check (warning_percent between 1 and 99),
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (monthly_limit_usd >= daily_limit_usd)
);

create table public.ai_usage_ledger (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  correlation_id uuid not null,
  intervention_id uuid,
  model text not null,
  input_tokens integer not null default 0 check (input_tokens >= 0),
  output_tokens integer not null default 0 check (output_tokens >= 0),
  cost_usd numeric(12, 6) not null check (cost_usd >= 0),
  source public.source_kind not null default 'ares',
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, intervention_id)
    references public.ares_interventions(tenant_id, id) on delete restrict
);

create index ai_usage_ledger_tenant_occurred_idx
  on public.ai_usage_ledger (tenant_id, occurred_at desc);

create table public.worker_ticks (
  id uuid primary key default gen_random_uuid(),
  worker_name text not null,
  acquired boolean not null,
  claimed_count integer not null default 0 check (claimed_count >= 0),
  succeeded_count integer not null default 0 check (succeeded_count >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  correlation_id uuid not null
);

alter table public.jobs
  add column if not exists finished_at timestamptz;

alter table public.ai_budget_limits enable row level security;
alter table public.ai_usage_ledger enable row level security;
alter table public.worker_ticks enable row level security;

create policy tenant_read_isolation
  on public.ai_budget_limits for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));

create policy tenant_read_isolation
  on public.ai_usage_ledger for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));

revoke all on public.ai_budget_limits, public.ai_usage_ledger, public.worker_ticks
  from anon, authenticated;
grant select on public.ai_budget_limits, public.ai_usage_ledger to authenticated;

create index if not exists memberships_active_user_tenant_idx
  on public.memberships (user_id, tenant_id)
  where active;
create index if not exists webhook_receipts_connection_idx
  on public.webhook_receipts (tenant_id, connection_id);
create index if not exists inbox_receipts_event_idx
  on public.inbox_receipts (tenant_id, event_id);
create index if not exists event_failures_job_idx
  on public.event_failures (tenant_id, job_id)
  where job_id is not null;

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

create or replace function private.invoke_ares_tick()
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  tick_url text;
  tick_secret text;
  request_id bigint;
begin
  select decrypted_secret into tick_url
  from vault.decrypted_secrets
  where name = 'ares_tick_url';

  select decrypted_secret into tick_secret
  from vault.decrypted_secrets
  where name = 'ares_tick_secret';

  if tick_url is null or tick_secret is null then
    return null;
  end if;

  select net.http_post(
    url := tick_url,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-ARES-Tick-Secret', tick_secret
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 5000
  ) into request_id;
  return request_id;
end
$$;

revoke all on function private.invoke_ares_tick() from public, anon, authenticated;

select cron.schedule(
  'ares-tick-every-minute',
  '* * * * *',
  'select private.invoke_ares_tick()'
)
where not exists (
  select 1 from cron.job where jobname = 'ares-tick-every-minute'
);
