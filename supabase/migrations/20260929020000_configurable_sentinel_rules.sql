-- Rule templates are evaluated by bounded backend SQL, never by tenant SQL.
alter table public.sentinel_schedules
  add column kind text not null default 'sla_overdue'
    check (kind in ('sla_overdue', 'unassigned', 'stale')),
  add column title text not null default 'SLA vencido'
    check (length(trim(title)) between 3 and 80),
  add column threshold_hours integer not null default 0
    check (threshold_hours between 0 and 720),
  add column created_at timestamptz not null default now(),
  add column archived_at timestamptz;

drop index public.sentinel_schedules_due_idx;
create index sentinel_schedules_due_idx on public.sentinel_schedules
  (next_run_at, tenant_id) where enabled and archived_at is null;
create index sentinel_schedules_tenant_active_idx on public.sentinel_schedules
  (tenant_id, rule_id) where enabled and archived_at is null;

create index sentinel_findings_tenant_rule_idx on public.sentinel_findings
  (tenant_id, rule_id, due_at desc);

-- The prior unique key (tenant, opportunity, rule, due_at) and tenant FK remain.
-- Archived rules retain findings and audit history without generating new scans.
