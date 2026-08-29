begin;

create extension if not exists pgtap with schema extensions;
select plan(8);

select has_table('public', 'ares_interventions', 'intervention root exists');
select has_column('public', 'recommendations', 'recommended_action', 'recommended action is explicit');
select has_column('public', 'action_executions', 'executed_action', 'executed action is explicit');
select has_column('public', 'outcomes', 'incremental_value', 'incremental value is explicit');

insert into auth.users (
  id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
  (
    '10000000-0000-0000-0000-000000000001', 'authenticated', 'authenticated',
    'seller-one@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  ),
  (
    '10000000-0000-0000-0000-000000000002', 'authenticated', 'authenticated',
    'outsider@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()
  );

insert into public.tenants (id, name, slug) values
  ('20000000-0000-0000-0000-000000000001', 'Tenant One', 'tenant-one'),
  ('20000000-0000-0000-0000-000000000002', 'Tenant Two', 'tenant-two');

insert into public.memberships (tenant_id, user_id, role) values
  (
    '20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'seller'
  );

set local role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000001","role":"authenticated","app_metadata":{"active_tenant_id":"20000000-0000-0000-0000-000000000001"}}',
  true
);

select results_eq(
  'select count(*) from public.tenants',
  array[1::bigint],
  'active member reads only the selected tenant'
);
select results_eq(
  'select count(*) from public.memberships',
  array[1::bigint],
  'active member reads membership inside selected tenant'
);

select set_config(
  'request.jwt.claims',
  '{"sub":"10000000-0000-0000-0000-000000000002","role":"authenticated","app_metadata":{"active_tenant_id":"20000000-0000-0000-0000-000000000001"}}',
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

select * from finish();
rollback;
