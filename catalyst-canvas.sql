-- =====================================================================
--  AI University · Catalyst Canvas  (live co-creation workshop board)
--  Run once in Supabase Studio → SQL Editor → New query → Run.
--  Safe to re-run: objects use IF NOT EXISTS / OR REPLACE.
--
--  Design rule (same as schema.sql and ai-maturity.sql): the browser holds
--  only the public anon key. Tables have RLS ON and NO policies, so nobody
--  reads or writes them directly. Every call goes through the SECURITY
--  DEFINER functions below, which validate input. A board is reachable only
--  by someone who knows its code; clearing a whole board needs the
--  facilitator key, stored as a SHA-256 hash.
--
--  Until this file is run, catalyst-canvas.html works in preview mode:
--  boards are kept in each browser and can be shared as a .json file.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------
-- 1. TABLES
-- ---------------------------------------------------------------------
create table if not exists public.cc_boards (
  code        text primary key check (code ~ '^[a-z0-9][a-z0-9-]{2,39}$'),
  title       text check (char_length(title) <= 80),
  session     jsonb not null default '{}'::jsonb,
  key_hash    text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.cc_notes (
  code        text not null references public.cc_boards(code) on delete cascade,
  id          text not null check (id ~ '^[A-Za-z0-9_-]{4,40}$'),
  board       text not null check (board in ('voc','opp')),
  lane        smallint not null default 0 check (lane between 0 and 3),
  color       smallint not null default 0 check (color between 0 and 3),
  body        text not null check (char_length(body) between 1 and 160),
  rx          real check (rx between 0 and 1),
  ry          real check (ry between 0 and 1),
  author      text check (char_length(author) <= 40),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (code, id)
);

create table if not exists public.cc_votes (
  code     text not null,
  note_id  text not null,
  voter    text not null check (voter ~ '^[A-Za-z0-9_-]{8,40}$'),
  primary key (code, note_id, voter),
  foreign key (code, note_id) references public.cc_notes(code, id) on delete cascade
);

alter table public.cc_boards enable row level security;
alter table public.cc_notes  enable row level security;
alter table public.cc_votes  enable row level security;
revoke all on public.cc_boards, public.cc_notes, public.cc_votes from anon, authenticated;

-- ---------------------------------------------------------------------
-- 2. HELPERS
-- ---------------------------------------------------------------------
create or replace function public.cc_check_code(p_code text)
returns void language plpgsql immutable as $$
begin
  if p_code is null or p_code !~ '^[a-z0-9][a-z0-9-]{2,39}$' then
    raise exception 'invalid board code';
  end if;
end $$;

-- ---------------------------------------------------------------------
-- 3. API
-- ---------------------------------------------------------------------

-- Create a board. Returns the facilitator key once (keep it in the browser).
create or replace function public.cc_create(p_code text, p_title text)
returns json language plpgsql security definer set search_path = public, extensions as $$
declare k text;
begin
  perform cc_check_code(p_code);
  if exists (select 1 from cc_boards where code = p_code) then
    return json_build_object('created', false);
  end if;
  k := encode(gen_random_bytes(18), 'hex');
  insert into cc_boards(code, title, key_hash)
  values (p_code, left(coalesce(p_title, ''), 80), encode(digest(k, 'sha256'), 'hex'));
  return json_build_object('created', true, 'key', k);
end $$;

-- Read a whole board. p_voter is this browser's anonymous voter id.
create or replace function public.cc_board(p_code text, p_voter text)
returns json language plpgsql stable security definer set search_path = public as $$
declare b record;
begin
  perform cc_check_code(p_code);
  select * into b from cc_boards where code = p_code;
  if not found then return json_build_object('exists', false); end if;
  return json_build_object(
    'exists', true,
    'title', b.title,
    'session', b.session,
    'updated', extract(epoch from b.updated_at),
    'notes', coalesce((
      select json_agg(json_build_object(
        'id', n.id, 'board', n.board, 'lane', n.lane, 'color', n.color,
        'text', n.body, 'rx', n.rx, 'ry', n.ry, 'author', n.author,
        'ts', extract(epoch from n.created_at) * 1000,
        'votes', (select count(*) from cc_votes v where v.code = n.code and v.note_id = n.id),
        'mine',  exists (select 1 from cc_votes v where v.code = n.code and v.note_id = n.id and v.voter = p_voter)
      ) order by n.created_at)
      from cc_notes n where n.code = p_code), '[]'::json)
  );
end $$;

-- Add or change a note (creates the board row if missing).
create or replace function public.cc_upsert_note(
  p_code text, p_id text, p_board text, p_lane int, p_color int,
  p_text text, p_rx real, p_ry real, p_author text)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform cc_check_code(p_code);
  insert into cc_boards(code) values (p_code) on conflict do nothing;
  if not exists (select 1 from cc_notes where code = p_code and id = p_id)
     and (select count(*) from cc_notes where code = p_code) >= 400 then
    raise exception 'board is full';
  end if;
  insert into cc_notes(code, id, board, lane, color, body, rx, ry, author)
  values (p_code, p_id, p_board, coalesce(p_lane,0), coalesce(p_color,0),
          left(btrim(p_text), 160), p_rx, p_ry, left(p_author, 40))
  on conflict (code, id) do update set
    lane = excluded.lane, color = excluded.color, body = excluded.body,
    rx = excluded.rx, ry = excluded.ry, updated_at = now();
  update cc_boards set updated_at = now() where code = p_code;
end $$;

create or replace function public.cc_delete_note(p_code text, p_id text)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform cc_check_code(p_code);
  delete from cc_notes where code = p_code and id = p_id;
  update cc_boards set updated_at = now() where code = p_code;
end $$;

-- One vote per voter per note; p_on = false removes it.
create or replace function public.cc_vote(p_code text, p_id text, p_voter text, p_on boolean)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform cc_check_code(p_code);
  if p_on then
    insert into cc_votes(code, note_id, voter) values (p_code, p_id, p_voter) on conflict do nothing;
  else
    delete from cc_votes where code = p_code and note_id = p_id and voter = p_voter;
  end if;
  update cc_boards set updated_at = now() where code = p_code;
end $$;

-- Title, shared timers and next steps.
create or replace function public.cc_save_session(p_code text, p_title text, p_session jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform cc_check_code(p_code);
  if pg_column_size(p_session) > 16000 then raise exception 'session too large'; end if;
  insert into cc_boards(code, title, session) values (p_code, left(p_title, 80), p_session)
  on conflict (code) do update set title = left(p_title, 80), session = p_session, updated_at = now();
end $$;

-- Delete every note on a board. Needs the facilitator key.
create or replace function public.cc_clear(p_code text, p_key text)
returns boolean language plpgsql security definer set search_path = public, extensions as $$
begin
  perform cc_check_code(p_code);
  if not exists (select 1 from cc_boards where code = p_code
                 and key_hash = encode(digest(coalesce(p_key,''), 'sha256'), 'hex')) then
    return false;
  end if;
  delete from cc_notes where code = p_code;
  update cc_boards set updated_at = now() where code = p_code;
  return true;
end $$;

-- ---------------------------------------------------------------------
-- 4. GRANTS — only the API functions are callable from the browser
-- ---------------------------------------------------------------------
revoke all on function public.cc_check_code(text) from public;
revoke all on function public.cc_create(text,text) from public;
revoke all on function public.cc_board(text,text) from public;
revoke all on function public.cc_upsert_note(text,text,text,int,int,text,real,real,text) from public;
revoke all on function public.cc_delete_note(text,text) from public;
revoke all on function public.cc_vote(text,text,text,boolean) from public;
revoke all on function public.cc_save_session(text,text,jsonb) from public;
revoke all on function public.cc_clear(text,text) from public;
grant execute on function public.cc_create(text,text) to anon, authenticated;
grant execute on function public.cc_board(text,text) to anon, authenticated;
grant execute on function public.cc_upsert_note(text,text,text,int,int,text,real,real,text) to anon, authenticated;
grant execute on function public.cc_delete_note(text,text) to anon, authenticated;
grant execute on function public.cc_vote(text,text,text,boolean) to anon, authenticated;
grant execute on function public.cc_save_session(text,text,jsonb) to anon, authenticated;
grant execute on function public.cc_clear(text,text) to anon, authenticated;
