begin;

create extension if not exists pgtap with schema extensions;
select plan(16);

select has_table('public', 'ares_interventions', 'intervention root exists');
select has_column('public', 'recommendations', 'recommended_action', 'recommended action is explicit');
select has_column('public', 'action_executions', 'executed_action', 'executed action is explicit');
select has_column('public', 'outcomes', 'incremental_value', 'incremental value is explicit');
select has_table('public', 'ai_budget_limits', 'AI budget limit exists before model usage');
select has_table('public', 'ai_usage_ledger', 'AI usage ledger exists');
select has_table('public', 'worker_ticks', 'worker tick audit exists');
select ok(
  (select relrowsecurity from pg_class where oid = 'public.ai_budget_limits'::regclass),
  'AI budget limits have RLS enabled'
);

insert into auth.users (
  id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
  (
    '11000000-0000-0000-0000-000000000001', 'authenticated', 'authenticated',
    'seller-one@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  ),
  (
    '11000000-0000-0000-0000-000000000002', 'authenticated', 'authenticated',
    'outsider@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  ),
  (
    '11000000-0000-0000-0000-000000000003', 'authenticated', 'authenticated',
    'manager@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  ),
  (
    '11000000-0000-0000-0000-000000000004', 'authenticated', 'authenticated',
    'admin@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  ),
  (
    '11000000-0000-0000-0000-000000000005', 'authenticated', 'authenticated',
    'new-user@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  );

insert into public.tenants (id, name, slug) values
  ('21000000-0000-0000-0000-000000000001', 'Tenant One', 'tenant-one'),
  ('21000000-0000-0000-0000-000000000002', 'Tenant Two', 'tenant-two');

-- M6: membership activation fails closed without a seat contract.
insert into public.tenant_billing_state (tenant_id,state,reason,changed_by) values
  ('21000000-0000-0000-0000-000000000001','active','pgtap synthetic contract','11000000-0000-0000-0000-000000000004'),
  ('21000000-0000-0000-0000-000000000002','active','pgtap synthetic contract','11000000-0000-0000-0000-000000000004');
insert into public.tenant_quotas (
  tenant_id, seats_limit, ai_daily_budget_brl, ai_monthly_budget_brl,
  usd_brl_rate, rate_source, updated_by
) values
  ('21000000-0000-0000-0000-000000000001', 10, 0, 0, 1, 'pgtap synthetic', '11000000-0000-0000-0000-000000000004'),
  ('21000000-0000-0000-0000-000000000002', 10, 0, 0, 1, 'pgtap synthetic', '11000000-0000-0000-0000-000000000004');

insert into public.memberships (tenant_id, user_id, role) values
  (
    '21000000-0000-0000-0000-000000000001',
    '11000000-0000-0000-0000-000000000001',
    'seller'
  ),
  (
    '21000000-0000-0000-0000-000000000001',
    '11000000-0000-0000-0000-000000000003',
    'manager'
  ),
  (
    '21000000-0000-0000-0000-000000000001',
    '11000000-0000-0000-0000-000000000004',
    'admin'
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11000000-0000-0000-0000-000000000001","role":"authenticated","app_metadata":{"active_tenant_id":"21000000-0000-0000-0000-000000000001"}}',
  true
);

select results_eq(
  'select count(*) from public.tenants',
  array[1::bigint],
  'active member reads only the selected tenant'
);
select results_eq(
  'select count(*) from public.memberships',
  array[3::bigint],
  'active member reads memberships only inside selected tenant'
);

select set_config(
  'request.jwt.claims',
  '{"sub":"11000000-0000-0000-0000-000000000002","role":"authenticated","app_metadata":{"active_tenant_id":"21000000-0000-0000-0000-000000000001"}}',
  true
);

select results_eq(
  'select count(*) from public.tenants',
  array[0::bigint],
  'user without membership cannot read selected tenant'
);
select results_eq(
  'select count(*) from public.memberships',
  array[0::bigint],
  'user without membership cannot read tenant memberships'
);

select set_config(
  'request.jwt.claims',
  '{"sub":"11000000-0000-0000-0000-000000000003","role":"authenticated","app_metadata":{"active_tenant_id":"21000000-0000-0000-0000-000000000001"}}',
  true
);

select lives_ok(
  $$insert into public.teams (tenant_id, name) values ('21000000-0000-0000-0000-000000000001', 'Manager Team')$$,
  'manager can create a team inside the active tenant'
);

select set_config(
  'request.jwt.claims',
  '{"sub":"11000000-0000-0000-0000-000000000001","role":"authenticated","app_metadata":{"active_tenant_id":"21000000-0000-0000-0000-000000000001"}}',
  true
);

select throws_ok(
  $$insert into public.teams (tenant_id, name) values ('21000000-0000-0000-0000-000000000001', 'Seller Team')$$,
  '42501',
  'new row violates row-level security policy for table "teams"',
  'seller cannot create a team'
);

select set_config(
  'request.jwt.claims',
  '{"sub":"11000000-0000-0000-0000-000000000004","role":"authenticated","app_metadata":{"active_tenant_id":"21000000-0000-0000-0000-000000000001"}}',
  true
);

select lives_ok(
  $$insert into public.memberships (tenant_id, user_id, role) values ('21000000-0000-0000-0000-000000000001', '11000000-0000-0000-0000-000000000005', 'seller')$$,
  'admin can add a tenant membership'
);

select set_config(
  'request.jwt.claims',
  '{"sub":"11000000-0000-0000-0000-000000000003","role":"authenticated","app_metadata":{"active_tenant_id":"21000000-0000-0000-0000-000000000001"}}',
  true
);

select throws_ok(
  $$insert into public.memberships (tenant_id, user_id, role) values ('21000000-0000-0000-0000-000000000001', '11000000-0000-0000-0000-000000000002', 'seller')$$,
  '42501',
  'new row violates row-level security policy for table "memberships"',
  'manager cannot add a tenant membership'
);

select * from finish();
rollback;
