-- Migration 0012: waitlist (bring the live signup table under version control).
--
-- The `waitlist` table was created directly in the Supabase dashboard (a "live edit"), so
-- it had no migration (CTO audit finding B3). This migration documents the table AS IT
-- EXISTS in production, so it is reproducible in a fresh environment and tracked in version
-- control. It is IDEMPOTENT and a NO-OP on the existing production table: create-table is
-- `if not exists`, enable-rls is idempotent, the policy is drop-and-recreate (identical),
-- and the grant is already held. Applying it to the live DB changes nothing meaningful.
--
-- SCOPE (owner decision, 2026-06-12): VERSION-CONTROL ONLY. The live table currently also
-- grants `anon` and `authenticated` the full set (SELECT/UPDATE/DELETE/TRUNCATE/...), a
-- dashboard-era artefact. RLS is ON with ONLY an anon-INSERT policy, so anon cannot in fact
-- SELECT/UPDATE/DELETE today (no policy permits it) and the table is write-only for public
-- sign-ups. Tightening those grants down to anon-INSERT-only (defense in depth) is a
-- DEFERRED follow-up the owner chose not to apply here; a later `00NN_waitlist_revoke.sql`
-- should `revoke all on public.waitlist from anon, authenticated;` then re-grant only
-- `insert` to anon. This migration deliberately does NOT change grants.
--
-- The live sign-up form posts to Google Sheets (SheetMonkey) today; this Supabase table is
-- the schema-of-record for a future Supabase-backed waitlist.

-- =====================================================================
-- The table (matches production exactly).
-- =====================================================================
create table if not exists public.waitlist (
    id         uuid        primary key default gen_random_uuid(),
    email      text        not null,
    contexts   text[]      not null default '{}'::text[],
    source     text        not null default 'website'::text,
    created_at timestamptz not null default now()
);

-- =====================================================================
-- RLS: the table is reachable by the public `anon` role (the sign-up form), so RLS is ON
-- and the ONLY policy lets anon INSERT a sign-up. There is deliberately NO select/update/
-- delete policy, so anon (and authenticated) can write a sign-up but never read or change
-- the list. Drop-and-recreate keeps this idempotent without altering behaviour.
-- =====================================================================
alter table public.waitlist enable row level security;

drop policy if exists "anon can insert a waitlist signup" on public.waitlist;
create policy "anon can insert a waitlist signup"
    on public.waitlist
    for insert
    to anon
    with check (true);

-- The minimal grant the public form needs. No-op on the live table (which already holds it);
-- correct for a fresh environment. Other live grants are intentionally left as-is here (see
-- the SCOPE note above); the deferred revoke migration tightens them.
grant insert on public.waitlist to anon;
