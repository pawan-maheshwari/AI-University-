-- CALIBRE assessment counter for ai-psychology-calibre.html
-- Run once in the Supabase SQL editor (project octgqicycwaxfsxaswjf).
-- Stores a single public number: how many people have completed the
-- CALIBRE assessment and downloaded their report. No personal data.

create table if not exists public.calibre_stats (
  id          int primary key default 1,
  completions bigint not null default 0,
  updated_at  timestamptz not null default now(),
  constraint calibre_stats_single_row check (id = 1)
);

insert into public.calibre_stats (id) values (1) on conflict (id) do nothing;

alter table public.calibre_stats enable row level security;

drop policy if exists "calibre stats readable" on public.calibre_stats;
create policy "calibre stats readable" on public.calibre_stats
  for select using (true);

-- Read the current count.
create or replace function public.calibre_count()
returns bigint
language sql
stable
security definer
set search_path = public
as $$
  select completions from public.calibre_stats where id = 1;
$$;

-- Add one completion and return the new count. The page calls this at most
-- once per browser per 24 hours, and only when all 28 statements are answered.
create or replace function public.calibre_increment()
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare n bigint;
begin
  update public.calibre_stats
     set completions = completions + 1, updated_at = now()
   where id = 1
  returning completions into n;
  return n;
end;
$$;

revoke all on function public.calibre_count()     from public;
revoke all on function public.calibre_increment() from public;
grant execute on function public.calibre_count()     to anon, authenticated;
grant execute on function public.calibre_increment() to anon, authenticated;
