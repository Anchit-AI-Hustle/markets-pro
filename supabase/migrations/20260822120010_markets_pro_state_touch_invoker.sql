-- mp_state_touch had no business being SECURITY DEFINER.
--
-- It sets one column on the row being written and needs no privilege its
-- caller does not already hold, so running it as the definer bought nothing
-- and left a definer-rights function reachable at /rest/v1/rpc/mp_state_touch
-- by anyone holding the publishable key. As SECURITY INVOKER it runs with the
-- caller's own rights, and the EXECUTE grants are dropped as well so it is not
-- an exposed endpoint at all -- a trigger fires through the trigger mechanism,
-- which does not consult the calling role's EXECUTE privilege.

create or replace function public.mp_state_touch()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function public.mp_state_touch() from public;
revoke all on function public.mp_state_touch() from anon;
revoke all on function public.mp_state_touch() from authenticated;
