-- AI Academia — certificate issuing and verification
-- Run once in the Supabase SQL editor.
--
-- Design notes:
--  * Credential codes are random, not derived from the holder's name. A derived code
--    can be computed by anyone, which makes verification meaningless.
--  * The base table is not readable by anon at all. Verification goes through a view
--    that exposes four columns and nothing else.
--  * Rows are only ever written by the issue-certificate Edge Function using the
--    service-role key, after a Razorpay signature has been verified server-side.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- certificates
create table if not exists public.certificates (
  id            uuid primary key default gen_random_uuid(),
  code          text not null unique,
  user_id       uuid not null references auth.users(id) on delete cascade,
  holder_name   text not null,
  track_id      text not null,
  track_label   text not null,
  issued_at     timestamptz not null default now(),
  status        text not null default 'valid' check (status in ('valid','revoked')),
  revoked_at    timestamptz,
  revoked_note  text,
  -- payment provenance, never exposed publicly
  payment_ref   text,
  order_ref     text,
  amount_paise  integer,
  constraint certificates_code_format check (code ~ '^AIU-[A-Z]{3,6}-[A-Z0-9]{6,10}$'),
  -- one live certificate per user per track; re-issue requires revoking the old one
  constraint certificates_user_track_unique unique (user_id, track_id)
);

create index if not exists certificates_code_idx    on public.certificates (code);
create index if not exists certificates_user_idx    on public.certificates (user_id);
create index if not exists certificates_order_idx   on public.certificates (order_ref);

-- ------------------------------------------------------------------------ RLS
alter table public.certificates enable row level security;

-- No anon policy at all: the base table is invisible to the public.
-- A signed-in learner may read their own certificates (used by the app to restore
-- a licence on a new device).
drop policy if exists "own certificates readable" on public.certificates;
create policy "own certificates readable"
  on public.certificates for select
  to authenticated
  using (auth.uid() = user_id);

-- Deliberately no insert/update/delete policies. Writes happen only via the
-- service-role key inside the Edge Function, which bypasses RLS.

-- ------------------------------------------------------- public verification view
-- security_invoker = off so the view can read the table on behalf of anon,
-- while still exposing only these four columns.
drop view if exists public.certificate_verification;
create view public.certificate_verification
  with (security_invoker = off) as
select
  c.code,
  c.holder_name,
  c.track_label,
  c.issued_at,
  c.status
from public.certificates c;

revoke all on public.certificate_verification from public, anon, authenticated;
grant select on public.certificate_verification to anon, authenticated;

comment on view public.certificate_verification is
  'Public certificate lookup. Exposes holder name, track, issue date and status only.';

-- ------------------------------------------------------------- code generation
-- Crockford-style alphabet: no I, L, O, U, so codes cannot be misread off a
-- printed certificate or misheard over the phone.
create or replace function public.generate_credential_code(p_track_id text)
returns text
language plpgsql
as $$
declare
  alphabet constant text := '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  prefix   text;
  body     text;
  candidate text;
  attempt  int := 0;
begin
  prefix := upper(regexp_replace(coalesce(p_track_id, 'gen'), '[^a-zA-Z]', '', 'g'));
  prefix := substr(prefix, 1, 4);
  if length(prefix) < 3 then
    prefix := rpad(prefix, 3, 'X');
  end if;

  loop
    attempt := attempt + 1;
    body := '';
    for i in 1..6 loop
      body := body || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    candidate := 'AIU-' || prefix || '-' || body;
    exit when not exists (select 1 from public.certificates where code = candidate);
    if attempt > 40 then
      raise exception 'could not allocate a unique credential code';
    end if;
  end loop;

  return candidate;
end;
$$;

-- ------------------------------------------------------------------ revocation
-- Called by an administrator, not by the app. Terms clause 8.
create or replace function public.revoke_certificate(p_code text, p_note text)
returns void
language sql
security definer
set search_path = public
as $$
  update public.certificates
     set status = 'revoked', revoked_at = now(), revoked_note = p_note
   where code = p_code;
$$;

revoke all on function public.revoke_certificate(text, text) from public, anon, authenticated;
