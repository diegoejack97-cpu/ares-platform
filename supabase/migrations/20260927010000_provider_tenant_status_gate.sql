-- A provider suspension revokes tenant product access, including direct Data API reads.
-- Billing degradation remains separate: it preserves reads and blocks writes/agents.
create or replace function private.has_tenant_role(
  target_tenant_id uuid,
  allowed_roles public.membership_role[] default null
)
returns boolean
language sql stable security definer set search_path = '' as $$
  select target_tenant_id = nullif(
    auth.jwt() -> 'app_metadata' ->> 'active_tenant_id', ''
  )::uuid
  and exists (
    select 1 from public.tenants t
    join public.memberships m on m.tenant_id=t.id
    where t.id=target_tenant_id and t.status='active'
      and m.user_id=(select auth.uid()) and m.active
      and (allowed_roles is null or m.role=any(allowed_roles))
  )
$$;

create or replace function public.can_access_tenant(target_tenant_id uuid)
returns boolean
language sql stable security definer set search_path = '' as $$
  select target_tenant_id = public.current_tenant_id()
  and exists (
    select 1 from public.tenants t
    join public.memberships m on m.tenant_id=t.id
    where t.id=target_tenant_id and t.status='active'
      and m.user_id=auth.uid() and m.active
  )
$$;
