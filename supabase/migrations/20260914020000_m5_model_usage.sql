-- One observation per generation run; historical default zeros remain untrusted.
create table public.model_usage (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id),
  run_id uuid not null,
  model_id text,
  status text not null check (status in ('observed','not_called','unavailable')),
  input_tokens integer check (input_tokens >= 0),
  output_tokens integer check (output_tokens >= 0),
  cached_input_tokens integer check (cached_input_tokens >= 0 and cached_input_tokens <= input_tokens),
  cost_usd numeric(18,9) check (cost_usd >= 0),
  pricing_version text,
  observed_at timestamptz not null default now(),
  unique (tenant_id,run_id),
  foreign key (tenant_id,run_id) references public.agent_runs(tenant_id,id),
  check ((status='observed' and input_tokens is not null and output_tokens is not null
    and cached_input_tokens is not null and model_id is not null)
    or (status<>'observed' and input_tokens is null and output_tokens is null
      and cached_input_tokens is null and cost_usd is null)),
  check ((cost_usd is null) = (pricing_version is null))
);
alter table public.model_usage enable row level security;
revoke all on public.model_usage from anon, authenticated;
grant select on public.model_usage to authenticated;
create policy model_usage_read on public.model_usage for select to authenticated
  using (private.has_tenant_role(tenant_id, array['admin','manager','auditor']::public.membership_role[]));
-- Ledger keeps exact calculated amounts and remains the input to the budget guard.
alter table public.ai_usage_ledger alter column cost_usd type numeric(18,9);
