-- Markets Pro per-user state.
--
-- Every object here is prefixed mp_ because this database is shared with
-- another application: nothing in this migration reads, writes or alters a
-- table that does not carry that prefix.
--
-- One row per (user, key). The browser already keeps settings, the paper book
-- and the watchlist in localStorage; signing in mirrors those same documents
-- here so a second device sees them. The shape is deliberately opaque to the
-- database -- it is the browser's own JSON -- because the client is the only
-- thing that interprets it, and a schema that had to be migrated in lockstep
-- with the front end would be a liability rather than a safeguard.

create table if not exists public.mp_state (
  user_id    uuid        not null references auth.users (id) on delete cascade,
  key        text        not null,
  value      jsonb       not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, key),
  -- A closed set: an unknown key is a bug in the client, not a feature, and
  -- silently accepting one would let a typo create state nothing ever reads.
  constraint mp_state_key_known check (
    key in ('settings', 'paper', 'watchlist', 'journey')
  ),
  -- These documents are a few kilobytes at most. The ceiling is not a
  -- performance tuning knob; it stops one account from parking arbitrary
  -- data in a database that belongs to someone else's application too.
  constraint mp_state_value_bounded check (pg_column_size(value) < 262144)
);

comment on table public.mp_state is
  'Markets Pro: per-user client state, mirrored from localStorage on sign-in.';

alter table public.mp_state enable row level security;

-- Four explicit policies rather than one FOR ALL: an insert whose user_id
-- points at a stranger must fail the WITH CHECK, and an update must be
-- checked on both the row it starts from and the row it becomes.
drop policy if exists mp_state_select_own on public.mp_state;
create policy mp_state_select_own on public.mp_state
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists mp_state_insert_own on public.mp_state;
create policy mp_state_insert_own on public.mp_state
  for insert to authenticated
  with check (auth.uid() = user_id);

drop policy if exists mp_state_update_own on public.mp_state;
create policy mp_state_update_own on public.mp_state
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists mp_state_delete_own on public.mp_state;
create policy mp_state_delete_own on public.mp_state
  for delete to authenticated
  using (auth.uid() = user_id);

-- updated_at is set by the database, never by the client: the client is the
-- party with an interest in lying about which copy is newer, and last-write
-- resolution across two devices depends on this being trustworthy.
create or replace function public.mp_state_touch()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists mp_state_touch on public.mp_state;
create trigger mp_state_touch
  before insert or update on public.mp_state
  for each row execute function public.mp_state_touch();
