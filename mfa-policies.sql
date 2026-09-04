-- =====================================================================
--  mfa-policies.sql  ·  run AFTER schema.sql
--
--  Makes MFA mean something. Without this, two-step sign-in is a screen
--  the browser shows and an attacker can skip. With it, Postgres itself
--  refuses to return confidential rows to a session that has not
--  completed the second step.
--
--  The clever part: the policy demands aal2 ONLY from accounts that have
--  actually enrolled a factor. Everyone else keeps working on aal1, so
--  turning this on locks nobody out.
--
--  These are RESTRICTIVE policies, so they AND with the ownership
--  policies from schema.sql instead of ORing with them.
-- =====================================================================

create policy "confidential data requires MFA when enrolled"
  on public.profile_private
  as restrictive
  to authenticated
  using (
    array[auth.jwt()->>'aal'] <@ (
      select case
        when count(id) > 0 then array['aal2']
        else array['aal1', 'aal2']
      end
      from auth.mfa_factors
      where auth.mfa_factors.user_id = auth.uid()
        and status = 'verified'
    )
  );

create policy "confidential writes require MFA when enrolled"
  on public.profile_private
  as restrictive
  to authenticated
  with check (
    array[auth.jwt()->>'aal'] <@ (
      select case
        when count(id) > 0 then array['aal2']
        else array['aal1', 'aal2']
      end
      from auth.mfa_factors
      where auth.mfa_factors.user_id = auth.uid()
        and status = 'verified'
    )
  );


-- The data-export function runs SECURITY DEFINER, which bypasses RLS.
-- Add the same check by hand so it cannot be used as a way around the above.
create or replace function public.export_my_data()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  result jsonb;
  enrolled int;
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;

  select count(*) into enrolled
    from auth.mfa_factors
   where user_id = auth.uid() and status = 'verified';

  if enrolled > 0 and coalesce(auth.jwt()->>'aal', 'aal1') <> 'aal2' then
    raise exception 'Enter your authenticator code before exporting your data.';
  end if;

  select jsonb_build_object(
    'exported_at', now(),
    'profile',  (select to_jsonb(p)  from public.profiles p         where p.id = auth.uid()),
    'private',  (select to_jsonb(pp) from public.profile_private pp where pp.user_id = auth.uid()),
    'consent',  (select coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb)
                   from public.consent_events c where c.user_id = auth.uid()),
    'progress', (select coalesce(jsonb_agg(to_jsonb(pr)), '[]'::jsonb)
                   from public.progress pr where pr.user_id = auth.uid())
  ) into result;

  return result;
end;
$$;

revoke all on function public.export_my_data() from anon;
grant execute on function public.export_my_data() to authenticated;


-- ---------------------------------------------------------------------
-- Check it worked. Signed in WITHOUT completing the second step, on an
-- account that has MFA enrolled, this must return zero rows:
--
--   select * from profile_private;
--
-- After entering the code, the same query returns your row.
-- ---------------------------------------------------------------------
