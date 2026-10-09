-- A missing commercial contract cannot authorize writes through the Data API.
-- Preserve membership isolation and the company's timezone for grace periods.
create or replace function private.billing_writable(target uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select private.has_tenant_role(target) and exists (
    select 1 from public.tenant_billing_state b
    join public.tenants t on t.id=b.tenant_id
    where b.tenant_id=target and t.status='active'
      and (b.state='active' or
        (b.state='past_due' and (now() at time zone t.timezone)::date<=b.grace_until))
  )
$$;
revoke all on function private.billing_writable(uuid) from public, anon;
grant execute on function private.billing_writable(uuid) to authenticated;
