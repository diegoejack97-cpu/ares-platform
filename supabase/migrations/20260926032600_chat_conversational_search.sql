-- Chat discovery starts without a selected opportunity; existing scoped conversations remain valid.
alter table public.conversations alter column opportunity_id drop not null;
create unique index conversations_one_general_per_owner
  on public.conversations(tenant_id,owner_user_id) where opportunity_id is null;

-- Only read-only chat runs may exist before a commercial context is selected.
alter table public.agent_runs alter column opportunity_id drop not null;
alter table public.agent_runs alter column context_ref drop not null;
alter table public.agent_runs add constraint agent_runs_commercial_context_required
  check(agent_name='chat' or (opportunity_id is not null and context_ref is not null));
