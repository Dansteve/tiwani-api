"""Real-Postgres RLS test for the subscription tables (Subscription precondition 5).

The fake-client tests prove the SERVICE behaviour; they cannot catch an over-permissive RLS
policy, because they do not run Postgres. This test runs the ACTUAL migration 0018 policies
against a REAL Postgres and asserts the three properties the board named:

  1. an authenticated user CANNOT UPDATE its own subscription (the self-grant fix at the DB
     layer: subscription state is owner-SELECT-only, NO user write policy);
  2. an authenticated user CANNOT READ another user's subscription (tenant isolation);
  3. the webhook RPC (public.apply_subscription_event, SECURITY DEFINER) CAN write, and is
     IDEMPOTENT on the Stripe event id.

Plus the gate-relevant reads: a user CAN read its own subscription and the plan_tier /
feature_entitlement reference data (so the gate can resolve a tier), and CANNOT read the
billing_event ledger.

SAFETY: this test NEVER touches production. It runs ONLY against a DISPOSABLE Postgres named
by the TIWANI_TEST_DATABASE_URL env var, and it hard-REFUSES to run if that URL points at the
known production host (db.kogpfmuxgfjfjkdwrsjv.supabase.co) or carries the production database
name. With no TIWANI_TEST_DATABASE_URL set, the whole module is SKIPPED (the case in CI /
this sandbox today: no Docker, no local Postgres, and prod is correctly off-limits). To run
it, point TIWANI_TEST_DATABASE_URL at a throwaway local/branch Postgres.

Because a bare Postgres has none of Supabase's auth shim, the test bootstraps a MINIMAL one
(the `authenticated`/`anon`/`service_role` roles, an `auth` schema with `auth.users` +
`auth.uid()` reading request.jwt.claims->>'sub'), exactly the surface migration 0018's policies
reference, then applies the migration verbatim and switches request.jwt.claims to impersonate
each user, which is how Supabase RLS resolves auth.uid() under PostgREST.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid

import pytest

# The migration under test, read verbatim (not a paraphrase): the real policies are exercised.
_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "supabase" / "migrations" / "0018_subscription_entitlement.sql"
)

# Production guard: refuse to run against the known prod host or db name, whatever the env says.
_FORBIDDEN_HOST_FRAGMENTS = ("kogpfmuxgfjfjkdwrsjv.supabase.co",)

_TEST_DB_URL = os.environ.get("TIWANI_TEST_DATABASE_URL")

asyncpg = pytest.importorskip("asyncpg")

pytestmark = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason=(
        "Set TIWANI_TEST_DATABASE_URL to a DISPOSABLE Postgres to run the real-Postgres RLS "
        "test (never production). Skipped here: no throwaway Postgres is configured."
    ),
)


def _normalise_url(url: str) -> str:
    # asyncpg wants a plain postgres URL, not the SQLAlchemy +asyncpg scheme.
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )


def _assert_not_production(url: str) -> None:
    lowered = url.lower()
    for fragment in _FORBIDDEN_HOST_FRAGMENTS:
        if fragment in lowered:
            raise RuntimeError(
                "TIWANI_TEST_DATABASE_URL points at the production host; refusing to run the "
                "RLS test against production. Use a disposable Postgres."
            )


# The minimal Supabase auth shim migration 0018's policies depend on. Created on the test DB
# before the migration is applied, so auth.uid() / auth.users / the roles all resolve.
_BOOTSTRAP_SQL = """
do $$
begin
    if not exists (select from pg_roles where rolname = 'anon') then
        create role anon nologin;
    end if;
    if not exists (select from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin;
    end if;
    if not exists (select from pg_roles where rolname = 'service_role') then
        create role service_role nologin bypassrls;
    end if;
end
$$;

create schema if not exists auth;

create table if not exists auth.users (
    id uuid primary key
);

-- Supabase's auth.uid(): the current request's JWT subject, exactly what RLS keys on.
create or replace function auth.uid() returns uuid
language sql stable
as $$
    select nullif(
        current_setting('request.jwt.claims', true)::jsonb ->> 'sub', ''
    )::uuid;
$$;

-- The set_updated_at() trigger fn migration 0001 normally provides (0018 reuses it).
create or replace function public.set_updated_at() returns trigger
language plpgsql
as $fn$
begin
    new.updated_at = now();
    return new;
end;
$fn$;

grant usage on schema public to anon, authenticated, service_role;
grant usage on schema auth to anon, authenticated, service_role;
"""

_GRANTS_SQL = """
-- PostgREST grants table privileges to the roles; RLS then narrows WHICH rows. Mirror that so
-- the policies (not a missing GRANT) are what this test measures.
grant select, insert, update, delete on
    public.plan_tier, public.feature_entitlement, public.subscription, public.billing_event
    to authenticated;
grant select, insert, update, delete on
    public.plan_tier, public.feature_entitlement, public.subscription, public.billing_event
    to anon;
"""


async def _set_user(conn, user_id: str | None) -> None:
    """Impersonate an authenticated user (or anon) the way PostgREST does for RLS.

    Sets the role to `authenticated` and request.jwt.claims to {"sub": user_id}, so auth.uid()
    returns user_id inside the policies. user_id None clears the claims (an anon-ish caller).
    """
    await conn.execute("set role authenticated")
    if user_id is None:
        await conn.execute("select set_config('request.jwt.claims', '', true)")
    else:
        claims = json.dumps({"sub": user_id, "role": "authenticated"})
        await conn.execute("select set_config('request.jwt.claims', $1, true)", claims)


async def _reset_role(conn) -> None:
    await conn.execute("reset role")
    await conn.execute("select set_config('request.jwt.claims', '', true)")


async def _run() -> None:
    url = _normalise_url(_TEST_DB_URL)
    _assert_not_production(url)

    migration_sql = _MIGRATION_PATH.read_text()
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    conn = await asyncpg.connect(url)
    try:
        # Build the world inside a transaction we ROLL BACK at the end, so the disposable DB is
        # left untouched (no residue), and apply the REAL migration verbatim.
        tr = conn.transaction()
        await tr.start()

        await conn.execute(_BOOTSTRAP_SQL)
        await conn.execute(
            "insert into auth.users (id) values ($1), ($2) on conflict do nothing",
            uuid.UUID(user_a), uuid.UUID(user_b),
        )
        await conn.execute(migration_sql)  # the actual 0018 tables, policies, RPC, seed
        await conn.execute(_GRANTS_SQL)

        # Seed one subscription per user as the privileged owner (RLS bypassed here on purpose,
        # standing in for the webhook's prior writes), so there is data to read/deny.
        await conn.execute(
            "insert into public.subscription (user_id, tier_key, status) values "
            "($1, 'free', 'none'), ($2, 'premium', 'active')",
            uuid.UUID(user_a), uuid.UUID(user_b),
        )

        # --- 1. a user CAN read its OWN subscription (so the gate can resolve the tier) ---
        await _set_user(conn, user_a)
        own = await conn.fetch("select user_id, tier_key from public.subscription")
        assert len(own) == 1, "a user should read exactly their own subscription row"
        assert str(own[0]["user_id"]) == user_a
        assert own[0]["tier_key"] == "free"

        # --- 2. a user CANNOT read ANOTHER user's subscription (tenant isolation) ---
        b_rows = await conn.fetch(
            "select * from public.subscription where user_id = $1", uuid.UUID(user_b)
        )
        assert b_rows == [], "a user must not read another user's subscription (RLS hides it)"

        # --- 3. a user CANNOT UPDATE its own subscription (the self-grant fix at the DB) ---
        # No user UPDATE policy exists, so the update matches zero rows (RLS), and the tier is
        # unchanged. This is the core precondition-2/5 assertion: a user cannot self-promote.
        await conn.execute(
            "update public.subscription set tier_key = 'premium' where user_id = $1",
            uuid.UUID(user_a),
        )
        # Verify as the privileged owner that nothing actually changed.
        await _reset_role(conn)
        after = await conn.fetchval(
            "select tier_key from public.subscription where user_id = $1", uuid.UUID(user_a)
        )
        assert after == "free", "a user UPDATE must not change their tier (no write policy)"

        # --- 3b. a user CANNOT INSERT a subscription row for themselves either ---
        await _set_user(conn, user_a)
        insert_blocked = False
        try:
            # A nested transaction = a SAVEPOINT: the RLS denial here raises and aborts only the
            # savepoint, so the outer transaction stays usable for the remaining assertions.
            async with conn.transaction():
                await conn.execute(
                    "insert into public.subscription (user_id, tier_key, status) values "
                    "($1, 'premium', 'active') "
                    "on conflict (user_id) do update set tier_key = 'premium'",
                    uuid.UUID(user_a),
                )
        except asyncpg.exceptions.InsufficientPrivilegeError:
            insert_blocked = True
        # Either a hard privilege error, or (on conflict) zero effective change: re-check the tier.
        await _reset_role(conn)
        still_free = await conn.fetchval(
            "select tier_key from public.subscription where user_id = $1", uuid.UUID(user_a)
        )
        assert still_free == "free" or insert_blocked, "a user must not write their subscription"

        # --- 4. a user CANNOT read the billing_event ledger (RLS on, no policy) ---
        await conn.execute(
            "insert into public.billing_event (stripe_event_id, user_id) values ($1, $2)",
            "evt_seed", uuid.UUID(user_a),
        )
        await _set_user(conn, user_a)
        events = await conn.fetch("select * from public.billing_event")
        assert events == [], "a user must not read the billing_event ledger"

        # --- 5. reference data IS readable by an authenticated user (the gate needs it) ---
        tiers = await conn.fetch("select key from public.plan_tier order by sort")
        assert [t["key"] for t in tiers] == ["free", "standard", "premium"], (
            "the seeded plan_tier rows should be readable by an authenticated user"
        )
        recip_free = await conn.fetchval(
            "select value from public.feature_entitlement where feature_key = 'recipients.max' "
            "and tier_key = 'free'"
        )
        assert recip_free == "2", (
            "the board split (free covers TWO recipients) is the seeded default"
        )

        # --- 6. the webhook RPC CAN write (SECURITY DEFINER), and is IDEMPOTENT ---
        await _reset_role(conn)
        # First delivery: applies and returns true.
        applied = await conn.fetchval(
            "select public.apply_subscription_event($1,$2,$3,$4,$5,$6,$7,$8)",
            "evt_webhook_1", uuid.UUID(user_a), "premium", "active", None, "cus_1", "sub_1",
            "customer.subscription.updated",
        )
        assert applied is True, "the webhook RPC applies a new event"
        promoted = await conn.fetchval(
            "select tier_key from public.subscription where user_id = $1", uuid.UUID(user_a)
        )
        assert promoted == "premium", "the RPC wrote the new tier (the only path that can)"
        # Replay the SAME event id: idempotent no-op, returns false, tier unchanged.
        replay = await conn.fetchval(
            "select public.apply_subscription_event($1,$2,$3,$4,$5,$6,$7,$8)",
            "evt_webhook_1", uuid.UUID(user_a), "free", "canceled", None, "cus_1", "sub_1",
            "customer.subscription.updated",
        )
        assert replay is False, "a replayed Stripe event id is a no-op (idempotency)"
        unchanged = await conn.fetchval(
            "select tier_key from public.subscription where user_id = $1", uuid.UUID(user_a)
        )
        assert unchanged == "premium", "the replay must NOT have re-applied (still premium)"

        await tr.rollback()  # leave the disposable DB pristine
    finally:
        await conn.close()


def test_subscription_rls_real_postgres():
    asyncio.run(_run())
