create table public.report_exports (
 id uuid primary key default gen_random_uuid(),tenant_id uuid not null references public.tenants(id),
 owner_id uuid not null references auth.users(id),format text not null check(format in ('csv','pdf')),
 days int not null check(days between 1 and 365),status text not null default 'queued'
 check(status in ('queued','running','ready','failed')),payload bytea,
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '1 hour'
);
alter table public.report_exports enable row level security;
revoke all on public.report_exports from public,anon,authenticated;
create index report_exports_expiry on public.report_exports(expires_at);
