create table public.lead_intake (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references public.tenants(id),
 owner_id uuid not null references auth.users(id), name text not null, email text, phone text,
 identity_hash text not null, idempotency_key uuid not null, fingerprint text not null,
 status text not null default 'pending' check(status in ('pending','creating','created','merged','discarded','uncertain')),
 version int not null default 1, target_subject_id uuid, external_id text, reason text,
 correlation_id uuid not null default gen_random_uuid(), created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(), unique(tenant_id,id), unique(tenant_id,idempotency_key),
 foreign key(tenant_id,target_subject_id) references public.subjects(tenant_id,id)
);
create index lead_intake_owner_idx on public.lead_intake(tenant_id,owner_id,id);
create table public.merge_operations (
 id uuid primary key default gen_random_uuid(),tenant_id uuid not null,lead_id uuid not null,
 target_subject_id uuid not null,actor_id uuid not null references auth.users(id), reason text not null,
 undone_at timestamptz,undone_by uuid references auth.users(id), created_at timestamptz not null default now(),
 foreign key(tenant_id,lead_id) references public.lead_intake(tenant_id,id),
 foreign key(tenant_id,target_subject_id) references public.subjects(tenant_id,id)
);
alter table public.lead_intake enable row level security;
alter table public.merge_operations enable row level security;
revoke all on public.lead_intake,public.merge_operations from public,anon,authenticated;
-- Only server routes expose scoped triage; no direct writes or broad tenant reads.
