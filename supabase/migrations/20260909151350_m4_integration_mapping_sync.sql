-- M4: additive integration state. Existing M1-M3 records are never reseeded.
create table public.tenant_entitlements (
  tenant_id uuid not null references public.tenants(id),
  module text not null check (module in ('stellar','ares_connect','ares_crm')),
  status text not null check (status in ('active','suspended','revoked')),
  granted_at timestamptz not null default now(), granted_by uuid not null,
  expires_at timestamptz, primary key (tenant_id,module)
);
create unique index one_funnel_owner_per_tenant on public.tenant_entitlements(tenant_id)
  where module in ('ares_connect','ares_crm') and status = 'active';
insert into public.tenant_entitlements(tenant_id,module,status,granted_by)
  select tenant_id,'ares_connect','active',user_id from public.memberships
  where tenant_id = '20000000-0000-0000-0000-000000000001' and active and role = 'admin'
  order by user_id limit 1;

alter table public.connections add column mapping_version integer not null default 0;
alter table public.deals add column connection_id uuid,
  add column external_version integer, add column canonical_stage text,
  add column source_changed_at timestamptz, add column is_missing boolean not null default false,
  add constraint deals_connection_fk foreign key(tenant_id,connection_id)
  references public.connections(tenant_id,id);
create index deals_connection_pipeline_idx on public.deals(tenant_id,connection_id,id);

create table public.connection_schema_snapshots (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
  connection_id uuid not null, version integer not null, schema_json jsonb not null,
  captured_at timestamptz not null default now(), actor_id uuid not null,
  unique(tenant_id,connection_id,version),
  foreign key(tenant_id,connection_id) references public.connections(tenant_id,id)
);
create table public.field_mappings (
  tenant_id uuid not null, connection_id uuid not null, mapping_version integer not null,
  canonical_field text not null, provider_path text not null,
  transformation text not null default 'identity' check(transformation in ('identity','uppercase')),
  required boolean not null default false, authority text not null default 'external'
  check(authority='external'), pii_class text not null default 'operational',
  primary key(tenant_id,connection_id,mapping_version,canonical_field),
  foreign key(tenant_id,connection_id) references public.connections(tenant_id,id)
);
create table public.stage_mappings (
  tenant_id uuid not null, connection_id uuid not null, mapping_version integer not null,
  external_stage text not null, canonical_stage text not null
  check(canonical_stage in ('new','qualification','proposal','negotiation','won','lost')),
  label text not null, position integer not null,
  primary key(tenant_id,connection_id,mapping_version,external_stage),
  unique(tenant_id,connection_id,mapping_version,canonical_stage),
  foreign key(tenant_id,connection_id) references public.connections(tenant_id,id)
);
create table public.sync_cursors (
  tenant_id uuid not null, connection_id uuid not null, entity_type text not null default 'deal',
  cursor text, watermark timestamptz, last_completed_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key(tenant_id,connection_id,entity_type),
  foreign key(tenant_id,connection_id) references public.connections(tenant_id,id)
);
create table public.external_records (
  tenant_id uuid not null, connection_id uuid not null, entity_type text not null default 'deal',
  external_id text not null, deal_id uuid not null, external_version integer not null,
  content_hash text not null, last_seen_run uuid, source_changed_at timestamptz,
  primary key(tenant_id,connection_id,entity_type,external_id),
  foreign key(tenant_id,connection_id) references public.connections(tenant_id,id),
  foreign key(tenant_id,deal_id) references public.deals(tenant_id,id)
);
create index external_records_deal_idx on public.external_records(tenant_id,deal_id);
create unique index one_active_integration_run on public.jobs(tenant_id,(payload->>'connection_id'))
  where kind='integration.sync' and status in ('queued','running');

do $$ declare tab text; begin
  foreach tab in array array['tenant_entitlements','connection_schema_snapshots','field_mappings',
    'stage_mappings','sync_cursors','external_records'] loop
    execute format('alter table public.%I enable row level security',tab);
    execute format('create policy tenant_read_isolation on public.%I for select to authenticated
      using ((select private.has_tenant_role(tenant_id)))',tab);
    execute format('revoke all on public.%I from anon,authenticated',tab);
    execute format('grant select on public.%I to authenticated',tab);
  end loop;
end $$;

-- Membership alone cannot grant a suspended module access to its integration data.
do $$ declare tab text; begin
  foreach tab in array array['connection_schema_snapshots','field_mappings',
    'stage_mappings','sync_cursors','external_records'] loop
    execute format('create policy active_connect_entitlement on public.%I as restrictive
      for select to authenticated using (exists(select 1 from public.tenant_entitlements e
      where e.tenant_id=%I.tenant_id and e.module=''ares_connect'' and e.status=''active''
      and (e.expires_at is null or e.expires_at>now())))',tab,tab);
  end loop;
end $$;
create policy mirrored_deal_entitlement on public.deals as restrictive for select to authenticated
  using (connection_id is null or exists(select 1 from public.tenant_entitlements e
    where e.tenant_id=deals.tenant_id and e.module='ares_connect' and e.status='active'
    and (e.expires_at is null or e.expires_at>now())));
