begin;

create extension if not exists pgtap with schema extensions;
select plan(16);

select has_table('public', 'signals', 'versioned signal ledger exists');
select has_table('public', 'opportunity_score_snapshots', 'score history exists');
select has_table('public', 'opportunity_state_transitions', 'state transition audit exists');
select has_column('public', 'signals', 'rule_version', 'each signal persists rule version');
select has_column('public', 'ares_opportunities', 'score_breakdown', 'current breakdown is queryable');
select has_column('public', 'context_snapshots', 'truncated', 'context truncation is explicit');
select has_column('public', 'context_snapshots', 'correlation_id', 'context keeps correlation');
select ok((select relrowsecurity from pg_class where oid = 'public.signals'::regclass), 'signals have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.opportunity_score_snapshots'::regclass), 'scores have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.opportunity_state_transitions'::regclass), 'transitions have RLS');
select has_index('public', 'ares_opportunities', 'ares_opportunities_radar_idx', 'Radar has tenant-first partial index');
select has_index('public', 'commercial_events', 'commercial_events_aggregate_timeline_idx', 'timeline has aggregate index');

insert into auth.users (id, aud, role, email, encrypted_password, email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
values
  ('12000000-0000-0000-0000-000000000001', 'authenticated', 'authenticated', 'm2-member@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now()),
  ('12000000-0000-0000-0000-000000000002', 'authenticated', 'authenticated', 'm2-outsider@example.test', '', now(), '{}'::jsonb, '{}'::jsonb, now(), now());
insert into public.tenants (id, name, slug) values ('22000000-0000-0000-0000-000000000001', 'M2 Tenant', 'm2-tenant');
-- M6: membership activation fails closed without a seat contract.
insert into public.tenant_quotas (tenant_id, seats_limit, ai_daily_budget_brl, ai_monthly_budget_brl, usd_brl_rate, rate_source, updated_by)
values ('22000000-0000-0000-0000-000000000001', 10, 0, 0, 1, 'pgtap synthetic', '12000000-0000-0000-0000-000000000001');
insert into public.memberships (tenant_id, user_id, role) values ('22000000-0000-0000-0000-000000000001', '12000000-0000-0000-0000-000000000001', 'seller');
insert into public.tenant_entitlements (tenant_id,module,status,granted_by)
values ('22000000-0000-0000-0000-000000000001','ares_connect','active','12000000-0000-0000-0000-000000000001');
insert into public.commercial_events (id, tenant_id, event_type, producer, aggregate_type, aggregate_id, correlation_id, actor_type, source, occurred_at, payload_hash)
values ('42000000-0000-0000-0000-000000000001', '22000000-0000-0000-0000-000000000001', 'deal.updated', 'test', 'deal', 'm2-deal', '52000000-0000-0000-0000-000000000001', 'external_system', 'crm', now(), 'hash');
insert into public.deals (id, tenant_id, title, external_id) values ('62000000-0000-0000-0000-000000000001', '22000000-0000-0000-0000-000000000001', 'M2 Deal', 'm2-deal');
insert into public.ares_opportunities (id, tenant_id, deal_id, opportunity_type, state, correlation_id, owner_user_id)
values ('72000000-0000-0000-0000-000000000001', '22000000-0000-0000-0000-000000000001', '62000000-0000-0000-0000-000000000001', 'revenue_recovery', 'prioritized', '52000000-0000-0000-0000-000000000001', '12000000-0000-0000-0000-000000000001');
insert into public.signals (tenant_id, event_id, opportunity_id, signal_type, rule_id, rule_version, severity, correlation_id)
values ('22000000-0000-0000-0000-000000000001', '42000000-0000-0000-0000-000000000001', '72000000-0000-0000-0000-000000000001', 'test', 'SIG-TEST', 'm2.1', 3, '52000000-0000-0000-0000-000000000001');
insert into public.opportunity_score_snapshots (tenant_id, opportunity_id, score_version, total_score, breakdown, input_hash, correlation_id)
values ('22000000-0000-0000-0000-000000000001', '72000000-0000-0000-0000-000000000001', 'm2.1', 0.5, '{"severity":{"value":0.5}}', 'score-hash', '52000000-0000-0000-0000-000000000001');

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"12000000-0000-0000-0000-000000000001","role":"authenticated","app_metadata":{"active_tenant_id":"22000000-0000-0000-0000-000000000001"}}', true);
select results_eq('select count(*) from public.signals', array[1::bigint], 'seller reads own signals with active plan');
select results_eq('select count(*) from public.opportunity_score_snapshots', array[1::bigint], 'seller reads own score history with active plan');

select set_config('request.jwt.claims', '{"sub":"12000000-0000-0000-0000-000000000002","role":"authenticated","app_metadata":{"active_tenant_id":"22000000-0000-0000-0000-000000000001"}}', true);
select results_eq('select count(*) from public.signals', array[0::bigint], 'outsider cannot read signals');
select results_eq('select count(*) from public.opportunity_score_snapshots', array[0::bigint], 'outsider cannot read scores');

select * from finish();
rollback;
