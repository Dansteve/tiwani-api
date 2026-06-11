-- Migration 0006: user_profile INSERT policy (own row).
--
-- 0001 created user_profile with SELECT + UPDATE policies for the owner but NO
-- insert policy, on the assumption that the row would be created server-side with
-- the service-role key. That key was never configured separately (the deployment
-- had the publishable/anon key in the service-role slot), so the lazy create in
-- get_or_create_profile failed with a 42501 RLS violation.
--
-- The correct, more secure design: the AUTHENTICATED user inserts their OWN
-- profile row under RLS, exactly as child_profile already allows. id == auth.uid()
-- (the table's PK references auth.users(id)), so a user can only ever create the
-- row keyed to themselves. No service-role key in the request path.
--
-- Idempotent (drop ... if exists), additive, no data change.

drop policy if exists user_profile_insert_own on public.user_profile;
create policy user_profile_insert_own
    on public.user_profile
    for insert
    with check (auth.uid() = id);
