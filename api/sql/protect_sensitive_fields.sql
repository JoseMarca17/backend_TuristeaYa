-- Protect column-level invariants in addition to row-level policies.
create or replace function private.protect_sensitive_fields()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if auth.uid() is null then return new; end if;
  if tg_table_name = 'user_access' then
   if old.user_id = auth.uid() and (new.role is distinct from old.role or new.status is distinct from old.status or new.user_id is distinct from old.user_id) then
    raise exception 'Cannot change own access' using errcode='42501';
   end if;
  end if;
  if private.has_role(array['admin']::text[]) then return new; end if;
  if tg_table_name = 'reviews' then
   if (new.hidden is distinct from old.hidden or new.user_id is distinct from old.user_id
      or new.place_id is distinct from old.place_id or new.id is distinct from old.id or new.created_at is distinct from old.created_at) then
    raise exception 'Review moderation fields require administrator' using errcode='42501';
   end if;
  end if;
  if tg_table_name = 'notifications' and (to_jsonb(new)-'read_at') is distinct from (to_jsonb(old)-'read_at') then
    raise exception 'Only read_at may be changed' using errcode='42501';
  end if;
  return new;
end;
$$;
revoke all on function private.protect_sensitive_fields() from public;
create trigger protect_review_fields before update on public.reviews for each row execute function private.protect_sensitive_fields();
create trigger protect_notification_fields before update on public.notifications for each row execute function private.protect_sensitive_fields();
create trigger protect_own_access before update on public.user_access for each row execute function private.protect_sensitive_fields();

create or replace function private.audit_review_moderation()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.hidden is distinct from old.hidden and auth.uid() is not null then
    insert into public.moderation_actions(review_id,moderator_id,action,reason)
    values(new.id,auth.uid(),case when new.hidden then 'hide' else 'keep' end,'Cambio de visibilidad por administrador');
    insert into public.audit_logs(actor_id,action,entity,entity_id,details)
    values(auth.uid(),'review_moderation','reviews',new.id,jsonb_build_object('hidden_before',old.hidden,'hidden_after',new.hidden));
  end if;
  return new;
end;
$$;
revoke all on function private.audit_review_moderation() from public;
create trigger audit_review_moderation after update of hidden on public.reviews for each row execute function private.audit_review_moderation();
