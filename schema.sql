-- =====================================================================
--  AI Academia / AI University  ·  Supabase schema
--  Run once in Supabase Studio → SQL Editor → New query → Run
--
--  Design rule: the browser only ever holds the anon key, which is
--  public by design. Every confidentiality guarantee below is enforced
--  by Row Level Security in Postgres, never by JavaScript.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. PROFILES  (low-sensitivity, the app reads this constantly)
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
  id              uuid primary key references auth.users(id) on delete cascade,
  display_name    text check (char_length(display_name) between 1 and 60),
  avatar_seed     text,                       -- for generated crest/avatar
  zone            text check (zone in ('sprouts','explorers','builders','architects','educators','leaders','elders')),
  locale          text default 'en',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "own profile: read"
  on public.profiles for select
  using (auth.uid() = id);

create policy "own profile: insert"
  on public.profiles for insert
  with check (auth.uid() = id);

create policy "own profile: update"
  on public.profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- No delete policy on purpose. Deleting the auth user cascades here,
-- and that has to go through the Edge Function so the audit trail is written.


-- ---------------------------------------------------------------------
-- 2. PROFILE_PRIVATE  (confidential: DOB, phone, school, guardian)
--    Separate table so a careless `select *` on profiles can never
--    leak it, and so you can revoke access at table granularity.
-- ---------------------------------------------------------------------
create table if not exists public.profile_private (
  user_id            uuid primary key references auth.users(id) on delete cascade,
  full_name          text,
  date_of_birth      date,
  phone              text,
  school_or_org      text,
  city               text,
  country            text,
  guardian_email     text,      -- required when the learner is a minor
  guardian_verified  boolean not null default false,
  notes              text,
  updated_at         timestamptz not null default now()
);

alter table public.profile_private enable row level security;

create policy "own private data: read"
  on public.profile_private for select
  using (auth.uid() = user_id);

create policy "own private data: write"
  on public.profile_private for insert
  with check (auth.uid() = user_id);

create policy "own private data: update"
  on public.profile_private for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Belt and braces: strip the blanket grants Supabase hands out, then
-- re-grant only what an authenticated session needs. anon gets nothing.
revoke all on public.profile_private from anon, authenticated;
grant select, insert, update on public.profile_private to authenticated;


-- ---------------------------------------------------------------------
-- 3. CONSENT  (DPDP Act 2023 — you already publish a DPDP privacy policy)
--    One immutable row per consent event. Never updated, only appended,
--    so you can prove what was agreed and when.
-- ---------------------------------------------------------------------
create table if not exists public.consent_events (
  id              bigserial primary key,
  user_id         uuid not null references auth.users(id) on delete cascade,
  purpose         text not null,      -- 'account', 'progress_tracking', 'digest_email'
  policy_version  text not null,      -- e.g. '2026-09-01'
  granted         boolean not null,
  recorded_at     timestamptz not null default now()
);

alter table public.consent_events enable row level security;

create policy "own consent: read"
  on public.consent_events for select
  using (auth.uid() = user_id);

create policy "own consent: append"
  on public.consent_events for insert
  with check (auth.uid() = user_id);

-- no update, no delete policy → append-only for everyone but service_role


-- ---------------------------------------------------------------------
-- 4. LEARNING PROGRESS  (per-zone, per-tool)
-- ---------------------------------------------------------------------
create table if not exists public.progress (
  user_id      uuid not null references auth.users(id) on delete cascade,
  tool_id      text not null,          -- '01_prompt_wizard', 'ai-library', ...
  state        jsonb not null default '{}'::jsonb,
  score        integer,
  updated_at   timestamptz not null default now(),
  primary key (user_id, tool_id)
);

alter table public.progress enable row level security;

create policy "own progress: all"
  on public.progress for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ---------------------------------------------------------------------
-- 5. AUDIT LOG on the confidential table
--    Written by a SECURITY DEFINER trigger, readable by nobody through
--    the API (no select policy) — only via service_role.
-- ---------------------------------------------------------------------
create table if not exists public.private_data_audit (
  id          bigserial primary key,
  user_id     uuid,
  action      text not null,
  changed_at  timestamptz not null default now(),
  changed_by  uuid default auth.uid()
);

alter table public.private_data_audit enable row level security;
-- deliberately zero policies: RLS on + no policy = no API access at all
revoke all on public.private_data_audit from anon, authenticated;

create or replace function public.log_private_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.private_data_audit (user_id, action)
  values (coalesce(new.user_id, old.user_id), tg_op);
  return coalesce(new, old);
end;
$$;

drop trigger if exists trg_private_audit on public.profile_private;
create trigger trg_private_audit
  after insert or update or delete on public.profile_private
  for each row execute function public.log_private_change();


-- ---------------------------------------------------------------------
-- 6. AUTO-CREATE the profile rows when someone signs up
-- ---------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1))
  )
  on conflict (id) do nothing;

  insert into public.profile_private (user_id)
  values (new.id)
  on conflict (user_id) do nothing;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();


-- ---------------------------------------------------------------------
-- 7. TOUCH updated_at
-- ---------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_touch_profiles on public.profiles;
create trigger trg_touch_profiles before update on public.profiles
  for each row execute function public.touch_updated_at();

drop trigger if exists trg_touch_private on public.profile_private;
create trigger trg_touch_private before update on public.profile_private
  for each row execute function public.touch_updated_at();

drop trigger if exists trg_touch_progress on public.progress;
create trigger trg_touch_progress before update on public.progress
  for each row execute function public.touch_updated_at();


-- ---------------------------------------------------------------------
-- 8. DPDP data-portability: one call returns everything held on you
-- ---------------------------------------------------------------------
create or replace function public.export_my_data()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare result jsonb;
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;

  select jsonb_build_object(
    'exported_at', now(),
    'profile',     (select to_jsonb(p) from public.profiles p where p.id = auth.uid()),
    'private',     (select to_jsonb(pp) from public.profile_private pp where pp.user_id = auth.uid()),
    'consent',     (select coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb)
                      from public.consent_events c where c.user_id = auth.uid()),
    'progress',    (select coalesce(jsonb_agg(to_jsonb(pr)), '[]'::jsonb)
                      from public.progress pr where pr.user_id = auth.uid())
  ) into result;

  return result;
end;
$$;

revoke all on function public.export_my_data() from anon;
grant execute on function public.export_my_data() to authenticated;


-- ---------------------------------------------------------------------
-- 9. Right to erasure: wipe the confidential row, keep the audit trail
--    (full auth.users deletion still needs the Edge Function in §10)
-- ---------------------------------------------------------------------
create or replace function public.erase_my_private_data()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;

  update public.profile_private
     set full_name = null, date_of_birth = null, phone = null,
         school_or_org = null, city = null, country = null,
         guardian_email = null, notes = null
   where user_id = auth.uid();
end;
$$;

revoke all on function public.erase_my_private_data() from anon;
grant execute on function public.erase_my_private_data() to authenticated;
