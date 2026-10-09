-- Finding conversations are personal and separate from general/opportunity chat.
alter table public.conversations add column finding_id uuid;
alter table public.conversations add foreign key(tenant_id,finding_id)
 references public.sentinel_findings(tenant_id,id);
alter table public.conversations drop constraint conversations_tenant_id_owner_user_id_opportunity_id_key;
create unique index conversations_one_opportunity_per_owner
 on public.conversations(tenant_id,owner_user_id,opportunity_id) where finding_id is null;
create unique index conversations_one_finding_per_owner
 on public.conversations(tenant_id,owner_user_id,finding_id) where finding_id is not null;

create table public.sentinel_chat_openings (
 tenant_id uuid not null references public.tenants(id),
 finding_id uuid not null,
 user_id uuid not null references auth.users(id),
 revision integer not null check(revision>0),
 context_hash text not null,
 message_id uuid not null,
 primary key(tenant_id,finding_id,user_id,revision,context_hash),
 foreign key(tenant_id,finding_id) references public.sentinel_findings(tenant_id,id),
 foreign key(tenant_id,message_id) references public.messages(tenant_id,id)
);
create table public.chat_feedback (
 tenant_id uuid not null references public.tenants(id),
 message_id uuid not null,
 user_id uuid not null references auth.users(id),
 rating text not null check(rating in ('helpful','unhelpful')),
 reason text not null default '' check(length(reason)<=500),
 run_id uuid not null,
 context_ref text not null,
 updated_at timestamptz not null default now(),
 primary key(tenant_id,message_id,user_id),
 foreign key(tenant_id,message_id) references public.messages(tenant_id,id),
 foreign key(tenant_id,run_id) references public.agent_runs(tenant_id,id)
);
alter table public.sentinel_chat_openings enable row level security;
alter table public.chat_feedback enable row level security;
revoke all on public.sentinel_chat_openings,public.chat_feedback from anon,authenticated;
-- Sellers use only the freshly authorized backend handoff; preserve browser table grants.
