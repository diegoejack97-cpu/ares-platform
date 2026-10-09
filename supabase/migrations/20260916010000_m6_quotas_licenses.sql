create table public.tenant_quotas (
 tenant_id uuid primary key references public.tenants(id),seats_limit int not null check(seats_limit>=0),
 ai_daily_budget_brl numeric(12,6) not null check(ai_daily_budget_brl>=0),
 ai_monthly_budget_brl numeric(12,6) not null check(ai_monthly_budget_brl>=ai_daily_budget_brl),
 usd_brl_rate numeric(14,8) not null check(usd_brl_rate>0),rate_source text not null check(length(trim(rate_source))>=3),
 updated_by uuid not null references auth.users(id),updated_at timestamptz not null default now()
);
create table public.tenant_usage_daily (
 tenant_id uuid not null references public.tenants(id),day date not null,
 ai_spend_brl numeric(18,8) not null default 0,agent_runs int not null default 0,
 primary key(tenant_id,day)
);
create table public.ai_budget_reservations (
 tenant_id uuid not null references public.tenants(id),run_id uuid not null,
 day date not null,estimated_usd numeric(18,8) not null check(estimated_usd>=0),
 usd_brl_rate numeric(14,8) not null,rate_source text not null,
 reserved_brl numeric(18,8) not null,actual_usd numeric(18,8),actual_brl numeric(18,8),
 status text not null check(status in ('reserved','settled','released','denied')),
 created_at timestamptz not null default now(),settled_at timestamptz,
 primary key(tenant_id,run_id)
);
create table public.tenant_invitations (
 id uuid primary key default gen_random_uuid(),tenant_id uuid not null references public.tenants(id),
 email text not null,role public.membership_role not null,status text not null default 'pending'
 check(status in ('pending','accepted','cancelled')),invited_by uuid not null references auth.users(id),
 accepted_by uuid references auth.users(id),created_at timestamptz not null default now(),version int not null default 1,
 unique(tenant_id,id)
);
create unique index pending_invitation_email on public.tenant_invitations(tenant_id,lower(email)) where status='pending';
do $$ declare target text; begin
 foreach target in array array['tenant_quotas','tenant_usage_daily','ai_budget_reservations','tenant_invitations'] loop
  execute format('alter table public.%I enable row level security',target);
  execute format('revoke all on public.%I from public,anon,authenticated',target);
 end loop;
end $$;
grant select on public.tenant_quotas,public.tenant_usage_daily to authenticated;
create policy quota_read on public.tenant_quotas for select to authenticated using(private.has_tenant_role(tenant_id));
create policy usage_read on public.tenant_usage_daily for select to authenticated using(private.has_tenant_role(tenant_id));

-- Activation is guarded even when performed through SQL or the Data API.
alter table public.memberships add column version int not null default 1;
create function private.check_membership_seat() returns trigger language plpgsql
security definer set search_path='' as $$
declare seat_cap int; used int;
begin
 if TG_OP='UPDATE' then new.version:=old.version+1; end if;
 if TG_OP='UPDATE' and new.tenant_id<>old.tenant_id then raise exception 'membership_tenant_immutable'; end if;
 if not new.active or (TG_OP='UPDATE' and old.active) then return new; end if;
 perform 1 from public.tenants where id=new.tenant_id for update;
 select seats_limit into seat_cap from public.tenant_quotas where tenant_id=new.tenant_id;
 -- Existing seed tenants are not changed on migration; new activations fail closed.
 if seat_cap is null then raise exception 'seat_contract_unconfigured'; end if;
 select count(*) into used from public.memberships where tenant_id=new.tenant_id and active and id<>new.id;
 used:=used+(select count(*) from public.tenant_invitations where tenant_id=new.tenant_id and status='pending');
 if used>=seat_cap then raise exception 'seat_limit_exceeded'; end if;
 return new;
end $$;
revoke all on function private.check_membership_seat() from public;
create trigger membership_seat_guard before insert or update on public.memberships
 for each row execute function private.check_membership_seat();
