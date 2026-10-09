alter table public.knowledge_documents add column origin_intervention_id uuid;
alter table public.knowledge_documents add constraint knowledge_episode_origin_fk
 foreign key(tenant_id,origin_intervention_id) references public.ares_interventions(tenant_id,id);
create index knowledge_episode_origin on public.knowledge_documents(tenant_id,origin_intervention_id)
 where origin_intervention_id is not null;
-- A corrected outcome makes derived knowledge unavailable, without deleting history.
create function private.invalidate_outcome_episodes() returns trigger language plpgsql
 security definer set search_path='' as $$
declare tenant uuid; intervention uuid;
begin
 if TG_OP='DELETE' then tenant:=OLD.tenant_id; intervention:=OLD.intervention_id;
 else tenant:=NEW.tenant_id; intervention:=NEW.intervention_id; end if;
 update public.knowledge_versions set status='superseded',error_code='outcome_source_changed'
  where tenant_id=tenant and document_id in
  (select id from public.knowledge_documents where tenant_id=tenant and origin_intervention_id=intervention);
 return null;
end $$;
revoke all on function private.invalidate_outcome_episodes() from public,anon,authenticated;
create trigger outcome_episode_correction after insert or update or delete on public.outcomes
 for each row execute function private.invalidate_outcome_episodes();
