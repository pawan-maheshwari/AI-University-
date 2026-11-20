-- =====================================================================
--  AI University · AI Maturity Assessment  (UNESCO AI Maturity Framework)
--  Run once in Supabase Studio → SQL Editor → New query → Run.
--  Safe to re-run: every object is created with IF NOT EXISTS / OR REPLACE.
--
--  Design rule (same as schema.sql): the browser only holds the public
--  anon key. Both tables have RLS ON and NO policies, so nobody can read
--  or write them directly. All access goes through the SECURITY DEFINER
--  functions below, which validate input and only ever return:
--    · aggregates (public dashboard), or
--    · one organisation's data, and only to a caller holding its admin key.
--  The admin key is stored as a SHA-256 hash, never in clear.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------
-- 1. TABLES
-- ---------------------------------------------------------------------
create table if not exists public.aim_orgs (
  id             uuid primary key default gen_random_uuid(),
  name           text not null check (char_length(name) between 2 and 120),
  country        text not null check (char_length(country) between 2 and 60),
  sector         text check (char_length(sector) <= 60),
  contact_name   text check (char_length(contact_name) <= 80),
  contact_email  text check (char_length(contact_email) <= 120),
  invite_code    text not null unique,
  admin_key_hash text not null,
  public_opt_in  boolean not null default false,  -- share anonymised results with the global dashboard
  created_at     timestamptz not null default now()
);

create table if not exists public.aim_responses (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid references public.aim_orgs(id) on delete cascade,  -- null = open access
  name          text not null check (char_length(name) between 1 and 80),
  country       text not null check (char_length(country) between 2 and 60),
  organisation  text not null check (char_length(organisation) between 1 and 120),
  role          text check (char_length(role) <= 80),
  department    text check (char_length(department) <= 80),
  scores        smallint[] not null,   -- 29 category levels, 1..4, framework order
  desired       smallint[],            -- 6 pillar target levels, 1..4
  pillars       numeric(3,2)[] not null,
  overall       numeric(3,2) not null,
  created_at    timestamptz not null default now()
);
create index if not exists aim_responses_org_idx     on public.aim_responses(org_id);
create index if not exists aim_responses_country_idx on public.aim_responses(country);

alter table public.aim_orgs      enable row level security;
alter table public.aim_responses enable row level security;
revoke all on public.aim_orgs, public.aim_responses from anon, authenticated;

-- ---------------------------------------------------------------------
-- 2. HELPERS
-- ---------------------------------------------------------------------
-- Pillar sizes in framework order: Strategy 5, People 5, Technology 4,
-- Operations 5, Governance 5, Data 5  (= 29 categories)
create or replace function public.aim_pillar_means(s smallint[])
returns numeric[] language plpgsql immutable as $$
declare sizes int[] := array[5,5,4,5,5,5]; out numeric[] := '{}'; i int; j int; pos int := 1; tot numeric;
begin
  for i in 1..6 loop
    tot := 0;
    for j in 1..sizes[i] loop tot := tot + s[pos]; pos := pos + 1; end loop;
    out := out || round(tot / sizes[i], 2);
  end loop;
  return out;
end $$;

create or replace function public.aim_band(x numeric)
returns int language sql immutable as $$
  select case when x < 1.75 then 1 when x < 2.5 then 2 when x < 3.25 then 3 else 4 end
$$;

-- ---------------------------------------------------------------------
-- 3. SPAM PROTECTION
--    Layers, all enforced here in Postgres (the browser can't skip them):
--    a) per-IP rate limits (IP is stored only as a salted SHA-256 hash)
--    b) a single-use "ticket" issued when an assessment starts; a submit
--       needs one at least 90 s old, so scripted bursts don't work
--    c) a honeypot field humans never see
--    d) no links or HTML in names / organisation / role / department
--    e) one submission per person + organisation per 24 h
--    f) Cloudflare Turnstile, switched on only when a secret is stored:
--         create extension if not exists http with schema extensions;
--         insert into public.aim_config(k,v) values ('turnstile_secret','<secret>')
--           on conflict (k) do update set v = excluded.v;
--       and set TURNSTILE_SITE_KEY in aiu-auth.js.
-- ---------------------------------------------------------------------
create table if not exists public.aim_config (k text primary key, v text not null);
create table if not exists public.aim_events (
  kind text not null, ip_hash text not null, created_at timestamptz not null default now());
create index if not exists aim_events_idx on public.aim_events(kind, ip_hash, created_at);
create table if not exists public.aim_tickets (
  id uuid primary key default gen_random_uuid(), ip_hash text not null,
  created_at timestamptz not null default now(), used_at timestamptz);
alter table public.aim_config  enable row level security;
alter table public.aim_events  enable row level security;
alter table public.aim_tickets enable row level security;
revoke all on public.aim_config, public.aim_events, public.aim_tickets from anon, authenticated;
insert into public.aim_config(k, v) values ('salt', encode(extensions.gen_random_bytes(16), 'hex'))
  on conflict (k) do nothing;
alter table public.aim_responses add column if not exists ip_hash text;
alter table public.aim_orgs      add column if not exists ip_hash text;

create or replace function public.aim_client_ip()
returns text language plpgsql stable as $$
declare h json; ip text;
begin
  begin h := nullif(current_setting('request.headers', true), '')::json;
  exception when others then h := null; end;
  ip := coalesce(h->>'cf-connecting-ip', split_part(h->>'x-forwarded-for', ',', 1), h->>'x-real-ip');
  return nullif(trim(ip), '');
end $$;

create or replace function public.aim_client_hash()
returns text language sql stable security definer set search_path = public as $$
  select encode(extensions.digest(coalesce(aim_client_ip(), 'unknown') ||
         (select v from aim_config where k = 'salt'), 'sha256'), 'hex')
$$;

-- Counts this caller's recent events of a kind, refuses past the limit, then logs one
create or replace function public.aim_rate(p_kind text, p_hash text, p_max int, p_window interval)
returns void language plpgsql security definer set search_path = public as $$
begin
  if random() < 0.02 then  -- light housekeeping
    delete from aim_events where created_at < now() - interval '2 days';
    delete from aim_tickets where created_at < now() - interval '2 days';
  end if;
  if (select count(*) from aim_events
       where kind = p_kind and ip_hash = p_hash and created_at > now() - p_window) >= p_max then
    raise exception 'Too many attempts from your network. Please try again later.';
  end if;
  insert into aim_events(kind, ip_hash) values (p_kind, p_hash);
end $$;

create or replace function public.aim_clean_text(p text, p_label text)
returns void language plpgsql immutable as $$
begin
  if p ~* '(https?://|www\.|<[a-z/!]|\.(com|net|ru|xyz|top)/)' then
    raise exception '% can''t contain links or HTML', p_label;
  end if;
end $$;

create or replace function public.aim_verify_captcha(p_token text)
returns void language plpgsql security definer set search_path = public, extensions as $$
declare v_secret text; v_res record; v_ok boolean;
begin
  select v into v_secret from aim_config where k = 'turnstile_secret';
  if v_secret is null or v_secret = '' then return; end if;   -- Turnstile not switched on
  if coalesce(p_token, '') = '' then raise exception 'Please complete the "I am human" check'; end if;
  begin
    execute $q$select status, content from extensions.http_post(
              'https://challenges.cloudflare.com/turnstile/v0/siteverify', $1, 'application/json')$q$
      into v_res
      using json_build_object('secret', v_secret, 'response', p_token, 'remoteip', aim_client_ip())::text;
  exception when undefined_function then
    raise exception 'Turnstile is configured but the http extension is not enabled';
  end;
  v_ok := coalesce((v_res.content::json->>'success')::boolean, false);
  if not v_ok then raise exception 'The "I am human" check failed. Please try again.'; end if;
end $$;

-- Called when someone starts an assessment
create or replace function public.aim_begin()
returns uuid language plpgsql security definer set search_path = public as $$
declare v_hash text := aim_client_hash(); v_id uuid;
begin
  perform aim_rate('begin', v_hash, 40, interval '1 hour');
  insert into aim_tickets(ip_hash) values (v_hash) returning id into v_id;
  return v_id;
end $$;

-- ---------------------------------------------------------------------
-- 4. ENROL AN ORGANISATION  → returns ids the browser shows once
-- ---------------------------------------------------------------------
drop function if exists public.aim_enroll_org(text,text,text,text,text,boolean);
create or replace function public.aim_enroll_org(
  p_name text, p_country text, p_sector text, p_contact_name text,
  p_contact_email text, p_public_opt_in boolean,
  p_hp text default null, p_captcha text default null)
returns json language plpgsql security definer set search_path = public as $$
declare v_id uuid; v_code text; v_key text; v_hash text := aim_client_hash();
begin
  if coalesce(p_hp, '') <> '' then raise exception 'Submission rejected'; end if;
  if coalesce(trim(p_name),'') = '' or coalesce(trim(p_country),'') = '' then
    raise exception 'Organisation name and country are required';
  end if;
  perform aim_clean_text(p_name, 'Organisation name');
  perform aim_clean_text(p_contact_name, 'Name');
  perform aim_verify_captcha(p_captcha);
  perform aim_rate('enrol_h', v_hash, 3,  interval '1 hour');
  perform aim_rate('enrol_d', v_hash, 10, interval '1 day');
  v_code := lower(encode(extensions.gen_random_bytes(6), 'hex'));
  v_key  := encode(extensions.gen_random_bytes(18), 'hex');
  insert into aim_orgs(name, country, sector, contact_name, contact_email, invite_code, admin_key_hash, public_opt_in, ip_hash)
  values (trim(p_name), trim(p_country), nullif(trim(p_sector),''), nullif(trim(p_contact_name),''),
          nullif(trim(p_contact_email),''), v_code, encode(extensions.digest(v_key, 'sha256'), 'hex'),
          coalesce(p_public_opt_in,false), v_hash)
  returning id into v_id;
  return json_build_object('org_id', v_id, 'invite_code', v_code, 'admin_key', v_key);
end $$;

-- What an associate sees when they open the private link
create or replace function public.aim_org_info(p_code text)
returns json language sql stable security definer set search_path = public as $$
  select json_build_object('name', name, 'country', country, 'sector', sector)
  from aim_orgs where invite_code = lower(trim(p_code))
$$;

-- ---------------------------------------------------------------------
-- 5. SUBMIT AN ASSESSMENT  (open access when p_code is null)
-- ---------------------------------------------------------------------
drop function if exists public.aim_submit(text,text,text,text,text,text,smallint[],smallint[]);
create or replace function public.aim_submit(
  p_code text, p_name text, p_country text, p_organisation text,
  p_role text, p_department text, p_scores smallint[], p_desired smallint[],
  p_ticket uuid default null, p_hp text default null, p_captcha text default null)
returns json language plpgsql security definer set search_path = public as $$
declare v_org aim_orgs; v_p numeric[]; v_overall numeric; v_id uuid; x smallint;
        v_hash text := aim_client_hash(); v_t aim_tickets; v_orgname text;
begin
  if coalesce(p_hp, '') <> '' then raise exception 'Submission rejected'; end if;
  if coalesce(trim(p_name),'') = '' or coalesce(trim(p_country),'') = '' then
    raise exception 'Name and country are required';
  end if;
  perform aim_clean_text(p_name, 'Name');
  perform aim_clean_text(p_organisation, 'Organisation');
  perform aim_clean_text(p_role, 'Role');
  perform aim_clean_text(p_department, 'Department');
  if array_length(p_scores,1) is distinct from 29 then raise exception 'Expected 29 category scores'; end if;
  foreach x in array p_scores loop
    if x is null or x < 1 or x > 4 then raise exception 'Scores must be 1-4'; end if;
  end loop;
  if p_desired is not null then
    if array_length(p_desired,1) is distinct from 6 then raise exception 'Expected 6 pillar targets'; end if;
    foreach x in array p_desired loop
      if x is null or x < 1 or x > 4 then raise exception 'Targets must be 1-4'; end if;
    end loop;
  end if;

  if p_code is not null and trim(p_code) <> '' then
    select * into v_org from aim_orgs where invite_code = lower(trim(p_code));
    if v_org.id is null then raise exception 'Unknown organisation link'; end if;
  else
    if coalesce(trim(p_organisation),'') = '' then raise exception 'Organisation is required'; end if;
  end if;
  v_orgname := coalesce(v_org.name, trim(p_organisation));

  -- ticket: issued at the start, single use, at least 90 seconds old
  select * into v_t from aim_tickets where id = p_ticket for update;
  if v_t.id is null or v_t.used_at is not null or v_t.created_at < now() - interval '1 day' then
    raise exception 'This assessment session has expired. Please reload the page and submit again.';
  end if;
  if v_t.created_at > now() - interval '90 seconds' then
    raise exception 'That was very fast. Please take time to read each category before submitting.';
  end if;

  perform aim_verify_captcha(p_captcha);

  -- associates of one organisation often share an office IP, so their limit is higher
  if v_org.id is null then
    perform aim_rate('open_h', v_hash, 5,  interval '1 hour');
    perform aim_rate('open_d', v_hash, 15, interval '1 day');
  else
    perform aim_rate('org_h', v_hash, 60,  interval '1 hour');
    perform aim_rate('org_d', v_hash, 300, interval '1 day');
  end if;

  if exists (select 1 from aim_responses
              where lower(name) = lower(trim(p_name)) and lower(organisation) = lower(v_orgname)
                and org_id is not distinct from v_org.id and created_at > now() - interval '1 day') then
    raise exception 'You have already submitted an assessment for this organisation today.';
  end if;

  update aim_tickets set used_at = now() where id = v_t.id;

  v_p := aim_pillar_means(p_scores);
  select round(avg(u),2) into v_overall from unnest(v_p) u;

  insert into aim_responses(org_id, name, country, organisation, role, department, scores, desired, pillars, overall, ip_hash)
  values (v_org.id, trim(p_name), trim(p_country), v_orgname,
          nullif(trim(p_role),''), nullif(trim(p_department),''), p_scores, p_desired, v_p, v_overall, v_hash)
  returning id into v_id;
  return json_build_object('id', v_id, 'overall', v_overall, 'pillars', v_p);
end $$;

-- ---------------------------------------------------------------------
-- 6. PUBLIC DASHBOARD  — aggregates only, no names, no organisations
--    Includes open-access responses + organisations that opted in.
-- ---------------------------------------------------------------------
create or replace function public.aim_public_stats()
returns json language sql stable security definer set search_path = public as $$
  with r as (
    select a.* from aim_responses a left join aim_orgs o on o.id = a.org_id
    where a.org_id is null or o.public_opt_in
  ), c as (
    select country, count(*) n, round(avg(overall),2) avg,
      json_build_array(
        count(*) filter (where aim_band(overall)=1), count(*) filter (where aim_band(overall)=2),
        count(*) filter (where aim_band(overall)=3), count(*) filter (where aim_band(overall)=4)) lv,
      json_build_array(round(avg(pillars[1]),2), round(avg(pillars[2]),2), round(avg(pillars[3]),2),
                       round(avg(pillars[4]),2), round(avg(pillars[5]),2), round(avg(pillars[6]),2)) pillars
    from r group by country
  )
  select json_build_object(
    'total',     (select count(*) from r),
    'orgs',      (select count(*) from aim_orgs),
    'avg',       (select round(avg(overall),2) from r),
    'pillars',   (select json_build_array(round(avg(pillars[1]),2), round(avg(pillars[2]),2), round(avg(pillars[3]),2),
                                          round(avg(pillars[4]),2), round(avg(pillars[5]),2), round(avg(pillars[6]),2)) from r),
    'categories',(select json_agg(v order by i) from (
                    select i, round(avg(scores[i]),2) v from r, generate_series(1,29) i group by i) q),
    'countries', (select coalesce(json_agg(c order by n desc), '[]'::json) from c),
    'updated',   now());
$$;

-- ---------------------------------------------------------------------
-- 7. ORGANISATION DASHBOARD  — needs the admin key
-- ---------------------------------------------------------------------
create or replace function public.aim_org_dashboard(p_org uuid, p_key text)
returns json language plpgsql stable security definer set search_path = public as $$
declare v_org aim_orgs; v json;
begin
  select * into v_org from aim_orgs
   where id = p_org and admin_key_hash = encode(extensions.digest(coalesce(p_key,''), 'sha256'), 'hex');
  if v_org.id is null then raise exception 'Invalid organisation or admin key'; end if;
  select json_build_object(
    'org', json_build_object('name', v_org.name, 'country', v_org.country, 'sector', v_org.sector,
                             'invite_code', v_org.invite_code, 'public_opt_in', v_org.public_opt_in,
                             'created_at', v_org.created_at),
    'responses', coalesce((select json_agg(json_build_object(
                   'name', name, 'country', country, 'role', role, 'department', department,
                   'scores', scores, 'desired', desired, 'pillars', pillars, 'overall', overall,
                   'created_at', created_at) order by created_at desc)
                 from aim_responses where org_id = v_org.id), '[]'::json),
    'updated', now())
  into v;
  return v;
end $$;

-- ---------------------------------------------------------------------
-- 8. GRANTS — only the functions are callable from the browser
-- ---------------------------------------------------------------------
revoke all on function public.aim_begin() from public;
revoke all on function public.aim_enroll_org(text,text,text,text,text,boolean,text,text) from public;
revoke all on function public.aim_org_info(text) from public;
revoke all on function public.aim_submit(text,text,text,text,text,text,smallint[],smallint[],uuid,text,text) from public;
revoke all on function public.aim_public_stats() from public;
revoke all on function public.aim_org_dashboard(uuid,text) from public;
revoke all on function public.aim_rate(text,text,int,interval) from public;
revoke all on function public.aim_verify_captcha(text) from public;
revoke all on function public.aim_client_hash() from public;
grant execute on function public.aim_begin() to anon, authenticated;
grant execute on function public.aim_enroll_org(text,text,text,text,text,boolean,text,text) to anon, authenticated;
grant execute on function public.aim_org_info(text) to anon, authenticated;
grant execute on function public.aim_submit(text,text,text,text,text,text,smallint[],smallint[],uuid,text,text) to anon, authenticated;
grant execute on function public.aim_public_stats() to anon, authenticated;
grant execute on function public.aim_org_dashboard(uuid,text) to anon, authenticated;
