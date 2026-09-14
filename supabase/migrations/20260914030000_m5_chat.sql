-- Conversation reads do not open a commercial intervention.
alter table public.agent_runs alter column intervention_id drop not null;
create table public.conversations (
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id),
 owner_user_id uuid not null references auth.users(id),
 opportunity_id uuid not null,
 created_at timestamptz not null default now(),
 unique(tenant_id,id), unique(tenant_id,owner_user_id,opportunity_id),
 foreign key(tenant_id,opportunity_id) references public.ares_opportunities(tenant_id,id)
);
create table public.messages (
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id),
 conversation_id uuid not null,
 run_id uuid not null,
 user_text text not null check(length(user_text) between 1 and 1200),
 assistant_text text not null default '',
 status text not null check(status in ('running','succeeded','failed')),
 context_json jsonb not null,
 tool_calls_json jsonb not null default '[]',
 created_at timestamptz not null default now(),
 unique(tenant_id,id),
 foreign key(tenant_id,conversation_id) references public.conversations(tenant_id,id),
 foreign key(tenant_id,run_id) references public.agent_runs(tenant_id,id)
);
create index messages_conversation_time on public.messages(tenant_id,conversation_id,created_at desc,id);
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
revoke all on public.conversations,public.messages from anon,authenticated;
grant select on public.conversations,public.messages to authenticated;
create policy conversations_read on public.conversations for select to authenticated using (
 owner_user_id=(select auth.uid()) and private.has_tenant_role(tenant_id,array['admin','manager']::public.membership_role[])
);
create policy messages_read on public.messages for select to authenticated using (
 exists(select 1 from public.conversations c where c.tenant_id=messages.tenant_id
   and c.id=messages.conversation_id and c.owner_user_id=(select auth.uid()))
);
