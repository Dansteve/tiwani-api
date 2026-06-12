-- Supabase-compatibility shim for the LOCAL / EPHEMERAL Postgres used by the
-- cross-user RLS integration test (tests/test_rls_isolation.py, CI job
-- "rls-isolation"). This file is NOT a production migration and is never
-- applied to the Supabase database: production already provides every object
-- recreated here. It exists so the real public migrations in
-- ../migrations/*.sql can be applied UNCHANGED to a bare `postgres:16` service
-- container, and the RLS policies (keyed to auth.uid()) execute for real.
--
-- The public migrations depend on exactly four Supabase-managed objects, all
-- recreated below to match Supabase's own definitions:
--   1. the roles `anon`, `authenticated`, `service_role` (migrations grant to
--      them and write `to authenticated` / `to anon` policies);
--   2. the `auth` schema;
--   3. `auth.users` (the FK target of every user-owned table's user_id / id);
--   4. `auth.uid()` (read in every `using` / `with check`), which returns the
--      `sub` claim from the per-request JWT GUC, exactly as Supabase defines it.
--
-- The test then "becomes user X" the same way PostgREST does on a real request:
-- it sets the role to `authenticated` and sets `request.jwt.claims` to
-- {"sub": "<user id>"} for the transaction, so auth.uid() resolves to that user
-- and RLS scopes every query to that user's rows. There is no second mechanism;
-- this is the genuine policy path, not a mock of it.

-- 1. Roles. NOLOGIN service roles, matching Supabase. IF NOT EXISTS via a guard
--    so the bootstrap is re-runnable.
do $$
begin
    if not exists (select from pg_roles where rolname = 'anon') then
        create role anon nologin noinherit;
    end if;
    if not exists (select from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin noinherit;
    end if;
    if not exists (select from pg_roles where rolname = 'service_role') then
        create role service_role nologin noinherit bypassrls;
    end if;
end
$$;

-- The connecting CI role needs to be able to SET ROLE to each of these to
-- impersonate a caller (authenticated) or the admin path (service_role).
grant anon, authenticated, service_role to current_user;

-- 2. The auth schema.
create schema if not exists auth;

-- 3. auth.users: only the columns the public migrations reference (the id, the
--    FK target). Supabase's real auth.users has many more columns; the
--    migrations only ever reference auth.users(id), so this is sufficient and
--    faithful for the FK + cascade behaviour the RLS test exercises.
create table if not exists auth.users (
    id    uuid primary key default gen_random_uuid(),
    email text
);

-- 4. auth.uid(): the per-request user id, read from the JWT claims GUC. This is
--    Supabase's own definition (extract the `sub` claim from
--    request.jwt.claims). The second arg `true` to current_setting means "return
--    NULL if unset" rather than erroring, so an unauthenticated request (no GUC)
--    yields NULL and every owner policy fails closed.
create or replace function auth.uid()
returns uuid
language sql
stable
as $$
    select nullif(
        current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
        ''
    )::uuid;
$$;

-- Some Supabase migrations also read auth.role(); none of TIWANI's do today,
-- but provide it for parity so a future migration applies unchanged.
create or replace function auth.role()
returns text
language sql
stable
as $$
    select nullif(
        current_setting('request.jwt.claims', true)::jsonb ->> 'role',
        ''
    )::text;
$$;

-- 5. Privileges, matching Supabase's default role grants. RLS decides WHICH ROWS a
--    role sees; the GRANTs below decide whether the role may touch the table at all.
--    On Supabase, anon/authenticated/service_role are granted usage on the schemas
--    and DML on the tables out of the box, and RLS narrows that to the owner's rows.
--    Without these grants, `set role authenticated` (or service_role) would hit
--    "permission denied for schema/relation" before a policy is ever evaluated, which
--    is NOT the behaviour we are testing. So we reproduce the default grants here.
--
--    Two parts: (a) grant on what already exists (the auth schema + auth.users), and
--    (b) ALTER DEFAULT PRIVILEGES so every table/sequence/function the migrations
--    create AFTER this shim is granted to the three roles automatically (the
--    migrations are run by current_user, so default privileges are keyed to it).

-- (a) the auth schema + auth.users (created above).
grant usage on schema auth to anon, authenticated, service_role;
grant select, insert, update, delete on auth.users to service_role;
-- authenticated/anon never touch auth.users directly in these tests, but a SELECT
-- right matches Supabase (auth.uid() reads claims, not the table) and is harmless.
grant select on auth.users to authenticated, anon;

-- (b) the public schema (the migrations create their tables here).
grant usage on schema public to anon, authenticated, service_role;

-- Default privileges for objects current_user creates from now on (the migrations).
alter default privileges for role current_user in schema public
    grant select, insert, update, delete on tables to anon, authenticated, service_role;
alter default privileges for role current_user in schema public
    grant usage, select on sequences to anon, authenticated, service_role;
alter default privileges for role current_user in schema public
    grant execute on functions to anon, authenticated, service_role;
