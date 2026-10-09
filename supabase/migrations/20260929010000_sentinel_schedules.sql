-- Tenant administrators schedule the fixed read-only SLA sentinel. The provider
-- still controls capacity through tenant_quotas.sentinel_slots.
create table public.sentinel_schedules (
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  rule_id text not null,
  enabled boolean not null default true,
  interval_minutes integer not null default 1
    check (interval_minutes in (1, 5, 15, 30, 60, 120, 360, 720, 1440)),
  start_time_local time without time zone not null default '00:00',
  next_run_at timestamptz not null default now(),
  last_run_at timestamptz,
  last_created_count integer check (last_created_count >= 0),
  version integer not null default 1 check (version > 0),
  updated_at timestamptz not null default now(),
  updated_by uuid,
  primary key (tenant_id, rule_id)
);

create index sentinel_schedules_due_idx on public.sentinel_schedules
  (next_run_at, tenant_id) where enabled;

insert into public.sentinel_schedules (tenant_id, rule_id)
select id, 'SENTINEL-SLA-OVERDUE' from public.tenants
on conflict do nothing;

create function private.seed_sentinel_schedule() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.sentinel_schedules (tenant_id, rule_id)
  values (new.id, 'SENTINEL-SLA-OVERDUE')
  on conflict do nothing;
  return new;
end;
$$;
revoke all on function private.seed_sentinel_schedule() from public, anon, authenticated;
create trigger tenant_seed_sentinel_schedule
after insert on public.tenants for each row
execute function private.seed_sentinel_schedule();

create table public.sentinel_schedule_audit (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  rule_id text not null,
  actor_user_id uuid not null,
  reason text not null check (length(trim(reason)) > 0),
  prior_config jsonb not null,
  next_config jsonb not null,
  correlation_id uuid not null default gen_random_uuid(),
  occurred_at timestamptz not null default now()
);
create index sentinel_schedule_audit_tenant_idx on public.sentinel_schedule_audit
  (tenant_id, occurred_at desc);

alter table public.sentinel_scan_runs
  add column tenant_id uuid references public.tenants(id) on delete restrict,
  add column rule_id text;
create index sentinel_scan_runs_tenant_checked_idx on public.sentinel_scan_runs
  (tenant_id, checked_at desc) where tenant_id is not null;

alter table public.sentinel_schedules enable row level security;
create policy sentinel_schedule_tenant_read on public.sentinel_schedules
  for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));
create policy sentinel_schedule_active_connect on public.sentinel_schedules
  as restrictive for select to authenticated
  using (exists (
    select 1 from public.tenant_entitlements e
    where e.tenant_id=sentinel_schedules.tenant_id
      and e.module='ares_connect' and e.status='active'
      and (e.expires_at is null or e.expires_at>now())
  ));
revoke all on public.sentinel_schedules from anon, authenticated;
grant select on public.sentinel_schedules to authenticated;

alter table public.sentinel_schedule_audit enable row level security;
revoke all on public.sentinel_schedule_audit from anon, authenticated;
