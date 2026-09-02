-- Deterministic tenant for the local M1 Event Journal adapter.
-- No real customer data or credentials belong in this file.
insert into public.tenants (id, name, slug)
values (
  '20000000-0000-0000-0000-000000000001',
  'ARES Local Development',
  'ares-local-development'
)
on conflict (id) do nothing;

insert into public.connections (
  id, tenant_id, provider, status, auth_type, capabilities
)
values (
  '30000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  'fake-crm',
  'healthy',
  'shared_secret',
  '{"read_deals":true,"create_task":true,"add_note":true,"update_stage":true}'::jsonb
)
on conflict (tenant_id, provider) do update
set status = excluded.status,
    capabilities = excluded.capabilities,
    updated_at = now();

insert into public.ai_budget_limits (
  tenant_id, daily_limit_usd, monthly_limit_usd, warning_percent
)
values (
  '20000000-0000-0000-0000-000000000001',
  1.00,
  10.00,
  80
)
on conflict (tenant_id) do update
set daily_limit_usd = excluded.daily_limit_usd,
    monthly_limit_usd = excluded.monthly_limit_usd,
    warning_percent = excluded.warning_percent,
    updated_at = now();
