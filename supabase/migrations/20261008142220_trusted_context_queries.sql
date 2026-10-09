-- General/read-only contexts share the snapshot store without replacing legacy
-- opportunity snapshots used as state-before/state-after for interventions.
alter table public.context_snapshots
  alter column opportunity_id drop not null,
  add column actor_id uuid references auth.users(id),
  add column purpose text,
  add column scope_kind text,
  add column scope_ref uuid,
  add column query_json jsonb,
  add column metadata_json jsonb,
  add column content_json jsonb,
  add column access_hash text,
  add column data_version bigint,
  add column cache_key text,
  add column valid_until timestamptz,
  add column token_budget integer,
  add constraint context_projection_budget check (
    actor_id is null or (token_budget=2500 and token_estimate<=token_budget
      and content_json is not null and cache_key is not null
      and purpose is not null and valid_until is not null)
  );
create index context_projection_cache_idx on public.context_snapshots
  (tenant_id,actor_id,cache_key,captured_at desc) where actor_id is not null;
create policy context_projection_author on public.context_snapshots
  as restrictive for select to authenticated
  using(actor_id is null or actor_id=(select auth.uid()));

create table private.context_data_versions (
  tenant_id uuid primary key references public.tenants(id) on delete cascade,
  version bigint not null default 1
);
alter table private.context_data_versions enable row level security;
revoke all on private.context_data_versions from public,anon,authenticated;
insert into private.context_data_versions(tenant_id) select id from public.tenants;

create function private.bump_context_data_version() returns trigger
-- Fixed table names and search path; clients cannot invoke this trigger function
-- or write counters directly. Authorized source-table writes still invalidate cache.
language plpgsql security definer set search_path=pg_catalog as $$
declare target uuid;
begin
  if tg_table_name='context_snapshots' then
    if coalesce(new.actor_id,old.actor_id) is not null then
      if tg_op='DELETE' then return old; else return new; end if;
    end if;
  end if;
  if tg_table_name='tenants' then
    target:=coalesce(new.id,old.id);
    if tg_op='DELETE' then return old; end if;
  else
    target:=coalesce(new.tenant_id,old.tenant_id);
  end if;
  -- Cascading deletion must not recreate a counter for a deleted tenant.
  if not exists(select 1 from public.tenants where id=target) then
    if tg_op='DELETE' then return old; else return new; end if;
  end if;
  insert into private.context_data_versions(tenant_id,version) values(target,1)
    on conflict(tenant_id) do update
    set version=private.context_data_versions.version+1;
  if tg_table_name<>'tenants' and tg_op='UPDATE' then
    if old.tenant_id<>new.tenant_id then
      insert into private.context_data_versions(tenant_id,version) values(old.tenant_id,1)
        on conflict(tenant_id) do update
        set version=private.context_data_versions.version+1;
    end if;
  end if;
  if tg_op='DELETE' then return old; else return new; end if;
end $$;
revoke all on function private.bump_context_data_version() from public,anon,authenticated;

do $$ declare tab text; begin
  foreach tab in array array['tenants','memberships','tenant_entitlements','connections',
    'deals','ares_opportunities','commercial_events','sync_cursors','external_records',
    'deal_stage_history','sentinel_schedules','sentinel_findings','ares_interventions','outcomes','context_snapshots'] loop
    execute format('create trigger bump_context_version after insert or update or delete
      on public.%I for each row execute function private.bump_context_data_version()',tab);
  end loop;
end $$;
