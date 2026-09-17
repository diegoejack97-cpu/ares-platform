create table public.tenant_billing_state (
  tenant_id uuid primary key references public.tenants(id) on delete restrict,
  state text not null check (state in ('active','past_due','degraded')),
  due_since date,
  grace_until date,
  reason text not null check (length(trim(reason)) >= 3),
  changed_by uuid not null references auth.users(id) on delete restrict,
  changed_at timestamptz not null default now(),
  check (state = 'active' or (due_since is not null and grace_until is not null
    and grace_until >= due_since))
);
alter table public.tenant_billing_state enable row level security;
revoke all on public.tenant_billing_state from public, anon, authenticated;
grant select on public.tenant_billing_state to authenticated;
create policy billing_tenant_read on public.tenant_billing_state
  for select to authenticated using (private.has_tenant_role(tenant_id));

-- Enforce the same write gate on direct Data API calls as on FastAPI.
create function private.billing_writable(target uuid) returns boolean
language sql stable security definer set search_path = '' as $$
 select private.has_tenant_role(target) and not exists (
   select 1 from public.tenant_billing_state b join public.tenants t on t.id=b.tenant_id
   where b.tenant_id=target and (b.state='degraded' or
     (b.state='past_due' and (now() at time zone t.timezone)::date>b.grace_until))
 )
$$;
revoke all on function private.billing_writable(uuid) from public;
grant execute on function private.billing_writable(uuid) to authenticated;
do $$ declare target text; begin
  for target in select tablename from pg_tables where schemaname='public'
    and tablename in (select table_name from information_schema.columns
                     where table_schema='public' and column_name='tenant_id')
  loop
    execute format('create policy billing_insert_gate on public.%I as restrictive for insert to authenticated with check (private.billing_writable(tenant_id))',target);
    execute format('create policy billing_update_gate on public.%I as restrictive for update to authenticated using (private.billing_writable(tenant_id)) with check (private.billing_writable(tenant_id))',target);
    execute format('create policy billing_delete_gate on public.%I as restrictive for delete to authenticated using (private.billing_writable(tenant_id))',target);
  end loop;
end $$;
