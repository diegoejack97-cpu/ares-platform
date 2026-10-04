-- Contracted capacity for the routines currently available in ARES Connect.
-- A value of zero disables that class of routine; existing contracts retain
-- their current behavior after this migration.
alter table public.tenant_quotas
  add column if not exists agent_slots integer not null default 1 check (agent_slots >= 0),
  add column if not exists sentinel_slots integer not null default 1 check (sentinel_slots >= 0);
