-- Provider identity is separate from tenant memberships. No user is promoted by this migration.
create table private.provider_operators (
 user_id uuid primary key references auth.users(id) on delete restrict,
 active boolean not null default true,
 reason text not null check(length(trim(reason)) > 0),
 created_at timestamptz not null default now()
);
create unique index one_active_provider_operator on private.provider_operators((true)) where active;
alter table private.provider_operators enable row level security;
revoke all on private.provider_operators from public,anon,authenticated;

create table public.provider_audit (
 id bigserial primary key,
 actor_id uuid not null references auth.users(id) on delete restrict,
 tenant_id uuid not null references public.tenants(id) on delete restrict,
 action text not null,
 before_state jsonb,
 after_state jsonb,
 reason text not null check(length(trim(reason)) > 0),
 at timestamptz not null default now(),
 correlation_id uuid not null default gen_random_uuid()
);
create index provider_audit_tenant_at on public.provider_audit(tenant_id,at desc,id);
alter table public.provider_audit enable row level security;
revoke all on public.provider_audit from public,anon,authenticated;
grant select on public.provider_audit to authenticated;
-- No product-role SELECT policy: the separate provider API is the only read path.
create function private.reject_provider_audit_mutation() returns trigger
language plpgsql set search_path='' as $$
begin
 raise exception 'provider_audit_is_immutable';
end;
$$;
revoke all on function private.reject_provider_audit_mutation() from public;
create trigger provider_audit_immutable before update or delete or truncate
 on public.provider_audit for each statement execute function private.reject_provider_audit_mutation();
