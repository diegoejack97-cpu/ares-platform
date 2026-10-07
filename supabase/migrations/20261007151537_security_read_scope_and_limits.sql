-- Interactive reads use the same ownership contract as Command Center:
-- seller = own portfolio; admin/manager/auditor = tenant-wide read.
-- Restrictive policies cannot be bypassed by older permissive tenant policies.
create or replace function private.can_read_portfolio(target_tenant uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select private.has_tenant_role(target_tenant,
    array['admin','manager','auditor']::public.membership_role[])
  and exists(select 1 from public.tenant_entitlements e
    where e.tenant_id=target_tenant and e.module='ares_connect' and e.status='active'
      and (e.expires_at is null or e.expires_at>now()))
$$;

create or replace function private.can_read_opportunity(target_tenant uuid, target_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select private.can_read_portfolio(target_tenant) or (
    private.has_tenant_role(target_tenant, array['seller']::public.membership_role[])
    and exists(select 1 from public.tenant_entitlements e
      where e.tenant_id=target_tenant and e.module='ares_connect' and e.status='active'
        and (e.expires_at is null or e.expires_at>now()))
    and exists(select 1 from public.ares_opportunities o
      where o.tenant_id=target_tenant and o.id=target_id and o.owner_user_id=auth.uid())
  )
$$;

create or replace function private.can_read_deal(target_tenant uuid, target_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select private.can_read_portfolio(target_tenant) or (
    private.has_tenant_role(target_tenant, array['seller']::public.membership_role[])
    and exists(select 1 from public.tenant_entitlements e
      where e.tenant_id=target_tenant and e.module='ares_connect' and e.status='active'
        and (e.expires_at is null or e.expires_at>now()))
    and (exists(select 1 from public.deals d where d.tenant_id=target_tenant
      and d.id=target_id and d.owner_user_id=auth.uid())
      or exists(select 1 from public.ares_opportunities o where o.tenant_id=target_tenant
        and o.deal_id=target_id and o.owner_user_id=auth.uid()))
  )
$$;

create or replace function private.can_read_intervention(target_tenant uuid, target_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select private.can_read_portfolio(target_tenant) or exists(
    select 1 from public.ares_interventions i where i.tenant_id=target_tenant
      and i.id=target_id and private.can_read_opportunity(target_tenant,i.opportunity_id))
$$;

create or replace function private.can_read_event(target_tenant uuid, target_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select private.can_read_portfolio(target_tenant) or exists(
    select 1 from public.commercial_events e where e.tenant_id=target_tenant and e.id=target_id
    and (exists(select 1 from public.signals s where s.tenant_id=target_tenant
      and s.event_id=e.id and private.can_read_opportunity(target_tenant,s.opportunity_id))
      or (e.intervention_id is not null and
        private.can_read_intervention(target_tenant,e.intervention_id))
      or (e.aggregate_type='opportunity' and exists(
        select 1 from public.ares_opportunities o where o.tenant_id=target_tenant
          and o.id::text=e.aggregate_id and private.can_read_opportunity(target_tenant,o.id)))
      or (e.aggregate_type='deal' and exists(
        select 1 from public.deals d where d.tenant_id=target_tenant
          and (d.id::text=e.aggregate_id or (d.external_id=e.aggregate_id
            and d.connection_id is not null and
            e.data->>'connection_id'=d.connection_id::text))
          and private.can_read_deal(target_tenant,d.id)))))
$$;

create or replace function private.can_read_graph_node(target_tenant uuid, target_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select private.can_read_portfolio(target_tenant) or exists(
    select 1 from public.graph_nodes n where n.tenant_id=target_tenant and n.id=target_id
    and ((n.kind='opportunity' and private.can_read_opportunity(target_tenant,n.ref_id))
      or (n.kind='deal' and private.can_read_deal(target_tenant,n.ref_id))
      or (n.kind in ('company','contact') and exists(
        select 1 from public.graph_edges e join public.graph_nodes d
          on d.tenant_id=e.tenant_id and d.id=e.src_id
        where e.tenant_id=target_tenant and e.dst_id=n.id and e.valid_until is null
          and d.kind='deal' and private.can_read_deal(target_tenant,d.ref_id)))))
$$;

revoke all on function private.can_read_portfolio(uuid),
  private.can_read_opportunity(uuid,uuid), private.can_read_deal(uuid,uuid),
  private.can_read_intervention(uuid,uuid), private.can_read_event(uuid,uuid),
  private.can_read_graph_node(uuid,uuid) from public, anon;
grant execute on function private.can_read_portfolio(uuid),
  private.can_read_opportunity(uuid,uuid), private.can_read_deal(uuid,uuid),
  private.can_read_intervention(uuid,uuid), private.can_read_event(uuid,uuid),
  private.can_read_graph_node(uuid,uuid) to authenticated;

create policy portfolio_read_scope on public.ares_opportunities as restrictive
  for select to authenticated using(private.can_read_opportunity(tenant_id,id));
create policy portfolio_read_scope on public.deals as restrictive
  for select to authenticated using(private.can_read_deal(tenant_id,id));
-- Canonical deals remain API-only: do not grant public.deals to browser roles.
-- This non-exposed, security-barrier view supplies the API's joins. Its owner
-- intentionally reads the table; the predicate revalidates the verified user's
-- tenant, persisted membership, active plan and ownership for EVERY row.
create view private.portfolio_deals with (security_barrier=true) as
  select d.id,d.tenant_id,d.title,d.external_id,d.external_stage,d.status,
    d.value,d.currency,d.last_activity_at,d.external_ref
  from public.deals d where private.can_read_deal(d.tenant_id,d.id);
revoke all on private.portfolio_deals from public,anon,authenticated;
grant select on private.portfolio_deals to authenticated;
create policy portfolio_read_scope on public.commercial_events as restrictive
  for select to authenticated using(private.can_read_event(tenant_id,id));
create policy portfolio_read_scope on public.graph_nodes as restrictive
  for select to authenticated using(private.can_read_graph_node(tenant_id,id));
create policy portfolio_read_scope on public.graph_edges as restrictive
  for select to authenticated using(private.can_read_graph_node(tenant_id,src_id)
    and private.can_read_graph_node(tenant_id,dst_id)
    and private.can_read_event(tenant_id,evidence_event_id));
create policy portfolio_read_scope on public.subjects as restrictive
  for select to authenticated using(private.can_read_portfolio(tenant_id) or exists(
    select 1 from public.deals d where d.tenant_id=subjects.tenant_id
      and d.subject_id=subjects.id and private.can_read_deal(d.tenant_id,d.id)));

do $$
declare item text;
begin
  foreach item in array array['context_snapshots','signals','opportunity_score_snapshots',
    'opportunity_state_transitions','ares_interventions','recommendations','approval_requests',
    'agent_runs','outcomes','sentinel_findings'] loop
    execute format('create policy portfolio_read_scope on public.%I as restrictive '
      'for select to authenticated using(private.can_read_opportunity(tenant_id,opportunity_id))', item);
  end loop;
  foreach item in array array['decisions','action_executions','action_intents','action_attempts'] loop
    execute format('create policy portfolio_read_scope on public.%I as restrictive '
      'for select to authenticated using(private.can_read_intervention(tenant_id,intervention_id))', item);
  end loop;
  foreach item in array array['external_records','deal_stage_history','external_write_dedup'] loop
    execute format('create policy portfolio_read_scope on public.%I as restrictive '
      'for select to authenticated using(private.can_read_deal(tenant_id,deal_id))', item);
  end loop;
  -- Operational payloads are not a shortcut around opportunity ownership.
  foreach item in array array['webhook_receipts','inbox_receipts','outbox_events','jobs',
    'event_failures','audit_log'] loop
    execute format('create policy portfolio_read_scope on public.%I as restrictive '
      'for select to authenticated using(private.can_read_portfolio(tenant_id))', item);
  end loop;
end $$;

create policy portfolio_read_scope on public.policy_decisions as restrictive
  for select to authenticated using(private.can_read_portfolio(tenant_id) or exists(
    select 1 from public.recommendations r where r.tenant_id=policy_decisions.tenant_id
      and r.id=policy_decisions.recommendation_id
      and private.can_read_opportunity(r.tenant_id,r.opportunity_id)));

alter table public.sentinel_scan_runs enable row level security;
revoke all on public.sentinel_scan_runs from public, anon, authenticated;
revoke all on function public.can_access_tenant(uuid) from public, anon;
grant execute on function public.can_access_tenant(uuid) to authenticated;

-- Shared token buckets: hashed user+tenant keys, no tokens, e-mail or IP addresses.
create table private.api_rate_buckets (
  key_hash text not null check(length(key_hash)=64),
  bucket text not null check(bucket in ('requests','writes','chat')),
  tokens double precision not null check(tokens>=0),
  updated_at timestamptz not null,
  primary key(key_hash,bucket)
);
alter table private.api_rate_buckets enable row level security;
revoke all on private.api_rate_buckets from public, anon, authenticated;
create index api_rate_buckets_expiry_idx on private.api_rate_buckets(updated_at);
create index commercial_events_page_idx on public.commercial_events(tenant_id,recorded_at desc,id desc);
