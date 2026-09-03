begin;

create extension if not exists pgtap with schema extensions;
select plan(24);

select has_table('public', 'agent_runs', 'agent runs are auditable');
select has_table('public', 'approval_requests', 'approval queue exists');
select has_table('public', 'action_intents', 'intent-level idempotency exists');
select has_table('public', 'action_attempts', 'execution attempts are correlated');
select has_column('public', 'recommendations', 'context_ref', 'recommendation freezes opaque context ref');
select has_column('public', 'recommendations', 'run_id', 'recommendation links agent run');
select has_column('public', 'recommendations', 'alternatives', 'alternatives are persisted');
select has_column('public', 'recommendations', 'contraindication', 'contraindication is explicit');
select has_column('public', 'recommendations', 'urgency', 'triage urgency is persisted');
select has_column('public', 'recommendations', 'generation_mode', 'AI degradation mode is explicit');
select has_column('public', 'recommendations', 'version', 'recommendation supports optimistic concurrency');
select has_column('public', 'decisions', 'edited_payload', 'edited-before-approve payload is preserved');
select has_column('public', 'action_executions', 'intent_id', 'execution links the authorized intent');
select has_column('public', 'policy_decisions', 'policy_hash', 'policy artifact hash is audited');

select ok((select relrowsecurity from pg_class where oid = 'public.agent_runs'::regclass), 'agent runs have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.approval_requests'::regclass), 'approvals have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.action_intents'::regclass), 'intents have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.action_attempts'::regclass), 'attempts have RLS');

select has_index('public', 'approval_requests', 'approvals_pending_idx', 'pending approvals have tenant-first index');
select has_index('public', 'action_intents', 'action_intents_status_idx', 'intent status has tenant-first index');
select has_index('public', 'action_attempts', 'action_attempts_intent_idx', 'attempt timeline is indexed');
select has_index('public', 'action_executions', 'action_executions_one_per_intent', 'one execution per intent is enforced');

select ok(
  not has_table_privilege('anon', 'public.action_intents', 'select,insert,update,delete'),
  'anonymous users have no intent access'
);
select ok(
  not has_table_privilege('authenticated', 'public.action_intents', 'insert,update,delete'),
  'client role cannot mutate action intents directly'
);

select * from finish();
rollback;
