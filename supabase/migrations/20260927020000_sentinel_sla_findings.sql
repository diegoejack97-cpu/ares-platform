-- A recurring read-only sentinel records its trigger once per SLA deadline.
-- CRM data and ARES opportunities retain their existing distinct identities.
create table public.sentinel_findings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  opportunity_id uuid not null,
  rule_id text not null,
  rule_version text not null,
  due_at timestamptz not null,
  evidence jsonb not null check (jsonb_typeof(evidence)='object'),
  correlation_id uuid not null,
  detected_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, opportunity_id, rule_id, due_at),
  foreign key (tenant_id, opportunity_id)
    references public.ares_opportunities(tenant_id, id) on delete restrict
);

create index sentinel_findings_tenant_due_idx
  on public.sentinel_findings (tenant_id, due_at, id);

create table public.sentinel_scan_runs (
  id uuid primary key default gen_random_uuid(),
  checked_at timestamptz not null default now(),
  created_count integer not null check (created_count >= 0)
);

revoke all on public.sentinel_scan_runs from anon, authenticated;

alter table public.sentinel_findings enable row level security;
create policy tenant_read_isolation on public.sentinel_findings
  for select to authenticated
  using ((select private.has_tenant_role(tenant_id)));
create policy active_connect_entitlement on public.sentinel_findings
  as restrictive for select to authenticated
  using (exists (
    select 1 from public.tenant_entitlements e
    where e.tenant_id=sentinel_findings.tenant_id
      and e.module='ares_connect' and e.status='active'
      and (e.expires_at is null or e.expires_at>now())
  ));

revoke all on public.sentinel_findings from anon, authenticated;
grant select on public.sentinel_findings to authenticated;
