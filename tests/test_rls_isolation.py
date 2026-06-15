"""Cross-user RLS isolation, proven end to end against a REAL Postgres.

This is the integration test the CTO review asked for (Docs/ExpertReviewFindings.md
M1): the Row Level Security policies on the v3 tables are CORRECT on paper, but
nothing executed them. Every OTHER suite in this repo runs against fakes (no live
database, sandbox-blocked), so they prove the api SENDS the right user-scoped query;
they cannot prove the DATABASE refuses a cross-user read. This file does, by applying
the real public migrations to an ephemeral Postgres and driving the policies the same
way a real request does.

How "be user X" works (the genuine policy path, not a mock of it):
  Supabase's auth.uid() returns the `sub` claim of the per-request JWT, which PostgREST
  exposes as the `request.jwt.claims` GUC. The CI shim (supabase/test/0000_supabase_shim.sql)
  recreates auth.uid() with that exact definition and the auth.users FK target and the
  anon/authenticated/service_role roles, so the public migrations apply UNCHANGED. To act
  as a user, the test sets role `authenticated` and sets `request.jwt.claims` to
  {"sub": "<user id>"} for the connection, exactly as a real signed-in request would, and
  RLS then scopes every query to that user. To seed across users it uses `service_role`
  (BYPASSRLS), the same privileged path the api's service-role client uses for admin writes.

What is proven (the headline isolation rule, for SELECT/INSERT/UPDATE/DELETE):
  - As user A, a plain read of an owner-scoped table returns ONLY A's rows (never B's).
  - As user A, a targeted read of a row that is provably B's returns ZERO rows (RLS hides
    it, not a 404 we wrote, the database itself).
  - As user A, an UPDATE / DELETE aimed at B's row affects ZERO rows (cannot mutate it).
  - As user A, an INSERT that tries to write a row owned by B is REJECTED by the
    `with check` (cannot plant a row under another owner).
  This is asserted on user_profile, child_profile, and activity_record (the foundation
  + the first user-data table), which share one policy shape, so a regression in the
  pattern is caught.

Wiring: the test requires a real Postgres at RLS_TEST_DATABASE_URL. The CI job
"rls-isolation" (.github/workflows/ci.yml) stands up a postgres:16 service, applies the
shim then every migration, and sets that env var. With the var UNSET (a normal dev box /
the existing fakes job) the whole module SKIPS, so the no-database suite stays green and
this never needs a live Supabase. It uses asyncpg, already a project dependency.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Optional

import pytest

asyncpg = pytest.importorskip("asyncpg")

# The real Postgres the policies run against, with the schema ALREADY APPLIED (the CI
# "rls-isolation" job applies supabase/test/0000_supabase_shim.sql then every migration
# via psql before invoking pytest). Unset on a dev box (and on the existing fakes-only
# CI job), so the entire module is skipped there; the dedicated CI job sets it.
RLS_TEST_DATABASE_URL: Optional[str] = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not RLS_TEST_DATABASE_URL,
    reason="RLS_TEST_DATABASE_URL is unset; this integration test needs a real Postgres "
    "(provided by the 'rls-isolation' CI job). The fakes-backed suites cover the rest.",
)

# A fixed chapter/codes for the activity_record rows (structured, engine-valid values).
_CHAPTER = "family"


async def _set_caller(conn: "asyncpg.Connection", user_id: Optional[str]) -> None:
    """Make the connection act as a specific signed-in user, the PostgREST way.

    Sets the role to `authenticated` and the request.jwt.claims GUC to {"sub": user_id},
    so the shim's auth.uid() resolves to user_id and RLS scopes to that user. Passing
    user_id=None simulates an unauthenticated caller (auth.uid() -> NULL). LOCAL to the
    transaction (is_local=true) so it never leaks between cases.
    """
    await conn.execute("set local role authenticated")
    claims = json.dumps({"sub": user_id} if user_id else {})
    # set_config(name, value, is_local=true): scope the GUC to this transaction only.
    await conn.execute("select set_config('request.jwt.claims', $1, true)", claims)


async def _as_service(conn: "asyncpg.Connection") -> None:
    """Switch the connection to the service_role (BYPASSRLS) for privileged seed writes."""
    await conn.execute("set local role service_role")


async def _seed_two_users(conn: "asyncpg.Connection") -> tuple[dict, dict]:
    """Seed two independent users (A and B), each with a profile, a child, and an activity.

    Written under service_role (BYPASSRLS), the same privileged path the api uses for its
    admin writes; the per-user reads under test then run as `authenticated`. Returns the two
    users' ids and their owned child_id / activity_id so the cross-user assertions can target
    a row they provably do NOT own.
    """
    await _as_service(conn)

    def _mk_user() -> dict:
        return {"id": str(uuid.uuid4())}

    user_a, user_b = _mk_user(), _mk_user()

    for label, user in (("a", user_a), ("b", user_b)):
        # auth.users (the FK target).
        await conn.execute(
            "insert into auth.users (id, email) values ($1, $2)",
            user["id"],
            f"user-{label}@example.test",
        )
        # user_profile.
        await conn.execute(
            "insert into public.user_profile (id, email, first_name) values ($1, $2, $3)",
            user["id"],
            f"user-{label}@example.test",
            f"User{label.upper()}",
        )
        # child_profile (the care recipient).
        child_id = str(uuid.uuid4())
        await conn.execute(
            "insert into public.child_profile (id, user_id, name, support_level_code) "
            "values ($1, $2, $3, $4)",
            child_id,
            user["id"],
            f"Child{label.upper()}",
            "SL-MED",
        )
        user["child_id"] = child_id
        # activity_record (the first user-data row). Cells sum to total (DB check).
        activity_id = str(uuid.uuid4())
        await conn.execute(
            """
            insert into public.activity_record (
                id, user_id, child_id, chapter, activity_code, activity_name,
                base_temporal, base_sensory, base_logistical, base_human,
                temporal, sensory, logistical, human, total, tier,
                scheduled_pulse_at
            ) values (
                $1, $2, $3, $4, 'routine-meal', 'A routine meal',
                2, 2, 2, 2,
                2, 2, 2, 2, 8, 'Full',
                now()
            )
            """,
            activity_id,
            user["id"],
            child_id,
            _CHAPTER,
        )
        user["activity_id"] = activity_id

        # card_record (the Card History rows): TWO cards per user, created a day apart, so
        # the paginated list (newest first + the keyset `before` cursor) has more than one
        # row to page and the cross-user / cursor isolation is provable.
        card_ids = []
        for n in range(2):
            card_id = str(uuid.uuid4())
            await conn.execute(
                """
                insert into public.card_record (
                    id, user_id, child_id, activity_id, token, content,
                    expires_at, created_at
                ) values (
                    $1, $2, $3, $4, $5, $6::jsonb,
                    now() + interval '30 days', now() - ($7 || ' days')::interval
                )
                """,
                card_id,
                user["id"],
                child_id,
                activity_id,
                f"token-{label}-{n}-{uuid.uuid4().hex}",
                json.dumps({"activity_name": f"Card {label}{n}", "chapter": _CHAPTER}),
                str(n),
            )
            card_ids.append(card_id)
        user["card_ids"] = card_ids

    return user_a, user_b


@pytest.fixture(scope="module")
def event_loop():
    """A module-scoped loop so the one connection is shared across the cases."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def rls_db(event_loop):
    """Connect once, seed two users, tear the connection down at the end.

    The schema (shim + every migration) is applied by the CI job BEFORE pytest runs, so
    this fixture only seeds the two users and yields the open connection. asyncpg parses
    the standard postgres:// URL; the api's DATABASE_URL uses the postgresql+asyncpg://
    SQLAlchemy form, so strip that prefix in case the same value is reused here.
    """
    url = RLS_TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgres://"
    )

    async def _connect_and_prepare():
        conn = await asyncpg.connect(url)
        # Seed in a transaction (the set_local role/GUC are transaction-scoped).
        async with conn.transaction():
            users = await _seed_two_users(conn)
        return conn, users

    conn, users = event_loop.run_until_complete(_connect_and_prepare())
    user_a, user_b = users
    try:
        yield conn, user_a, user_b
    finally:
        event_loop.run_until_complete(conn.close())


def _run(event_loop, coro):
    return event_loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# child_profile: the foundation user-data table.
# ---------------------------------------------------------------------------

def test_user_a_select_child_profile_sees_only_own_row(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            rows = await conn.fetch("select id, user_id from public.child_profile")
        return rows

    rows = _run(event_loop, _check())
    owner_ids = {str(r["user_id"]) for r in rows}
    # Exactly A's data, never B's. If the SELECT policy leaked, B's user_id would appear.
    assert owner_ids == {user_a["id"]}, f"cross-user leak: A saw owners {owner_ids}"
    assert user_b["id"] not in owner_ids


def test_user_a_cannot_target_user_b_child_row(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            # Ask, as A, for B's specific row by its primary key. RLS must hide it.
            row = await conn.fetchrow(
                "select id from public.child_profile where id = $1", user_b["child_id"]
            )
        return row

    row = _run(event_loop, _check())
    assert row is None, "RLS leak: user A could read user B's child_profile row by id"


def test_user_a_cannot_update_user_b_child_row(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            status = await conn.execute(
                "update public.child_profile set name = 'HACKED' where id = $1",
                user_b["child_id"],
            )
        return status

    status = _run(event_loop, _check())
    # asyncpg returns "UPDATE <n>"; RLS must make n == 0 (B's row is invisible to A).
    assert status.split()[-1] == "0", f"RLS leak: A updated B's row ({status})"

    # And confirm B's row is untouched, read back as B.
    async def _verify_as_b():
        async with conn.transaction():
            await _set_caller(conn, user_b["id"])
            row = await conn.fetchrow(
                "select name from public.child_profile where id = $1", user_b["child_id"]
            )
        return row

    row = _run(event_loop, _verify_as_b())
    assert row is not None and row["name"] != "HACKED"


def test_user_a_cannot_delete_user_b_child_row(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            status = await conn.execute(
                "delete from public.child_profile where id = $1", user_b["child_id"]
            )
        return status

    status = _run(event_loop, _check())
    assert status.split()[-1] == "0", f"RLS leak: A deleted B's row ({status})"


def test_user_a_cannot_insert_child_owned_by_user_b(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            # Try to plant a row under B's ownership. The `with check (auth.uid() = user_id)`
            # must reject it (a 42501 RLS violation).
            await conn.execute(
                "insert into public.child_profile (user_id, name, support_level_code) "
                "values ($1, $2, $3)",
                user_b["id"],
                "PlantedByA",
                "SL-LOW",
            )

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        _run(event_loop, _check())


# ---------------------------------------------------------------------------
# activity_record: the first user-DATA table (same policy shape).
# ---------------------------------------------------------------------------

def test_user_a_select_activity_record_sees_only_own_row(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            rows = await conn.fetch("select user_id from public.activity_record")
        return rows

    rows = _run(event_loop, _check())
    owner_ids = {str(r["user_id"]) for r in rows}
    assert owner_ids == {user_a["id"]}, f"cross-user leak on activity_record: {owner_ids}"


def test_user_b_select_activity_record_sees_only_own_row(rls_db, event_loop):
    """Symmetry: B sees only B (so case 1 was not an accident of which row was queried)."""
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_b["id"])
            rows = await conn.fetch("select user_id from public.activity_record")
        return rows

    rows = _run(event_loop, _check())
    owner_ids = {str(r["user_id"]) for r in rows}
    assert owner_ids == {user_b["id"]}, f"cross-user leak on activity_record: {owner_ids}"


def test_user_a_cannot_read_user_b_activity_by_id(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            row = await conn.fetchrow(
                "select id from public.activity_record where id = $1", user_b["activity_id"]
            )
        return row

    row = _run(event_loop, _check())
    assert row is None, "RLS leak: A could read B's activity_record by id"


# ---------------------------------------------------------------------------
# card_record: the Card History list (paginated, newest first + the keyset cursor)
# stays scoped to the caller. The pagination change reads card_record directly with
# an `order by created_at desc limit N` and an optional `created_at < before` filter,
# so prove that read can never cross users at the database (RLS, not just the app).
# ---------------------------------------------------------------------------

def test_user_a_paginated_card_list_sees_only_own_rows(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            # The exact shape the paginated list_cards issues: own rows, newest first,
            # capped. RLS must restrict it to A's cards even with the bound.
            rows = await conn.fetch(
                "select id, user_id from public.card_record "
                "order by created_at desc limit 50"
            )
        return rows

    rows = _run(event_loop, _check())
    owner_ids = {str(r["user_id"]) for r in rows}
    assert owner_ids == {user_a["id"]}, f"cross-user leak on card_record: {owner_ids}"
    # A's two seeded cards are visible; B's are not.
    ids = {str(r["id"]) for r in rows}
    assert ids == set(user_a["card_ids"])
    assert not ids & set(user_b["card_ids"])


def test_user_a_load_more_cursor_never_pages_into_user_b(rls_db, event_loop):
    """The keyset `before` cursor stays RLS-scoped: A paging older cards never sees B's."""
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            # A "Load more" with a wide-open cursor (now + 1 day): every row older than the
            # cursor. RLS must still hand back ONLY A's cards, never B's, however far it pages.
            rows = await conn.fetch(
                "select user_id from public.card_record "
                "where created_at < now() + interval '1 day' "
                "order by created_at desc limit 50"
            )
        return rows

    rows = _run(event_loop, _check())
    owner_ids = {str(r["user_id"]) for r in rows}
    assert owner_ids == {user_a["id"]}, f"RLS leak paging card_record: {owner_ids}"


def test_user_a_cannot_read_user_b_card_by_id(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            row = await conn.fetchrow(
                "select id from public.card_record where id = $1", user_b["card_ids"][0]
            )
        return row

    row = _run(event_loop, _check())
    assert row is None, "RLS leak: A could read B's card_record row by id"


# ---------------------------------------------------------------------------
# user_profile: a user sees only their own profile row.
# ---------------------------------------------------------------------------

def test_user_a_select_user_profile_sees_only_own_row(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, user_a["id"])
            rows = await conn.fetch("select id from public.user_profile")
        return rows

    rows = _run(event_loop, _check())
    ids = {str(r["id"]) for r in rows}
    assert ids == {user_a["id"]}, f"cross-user leak on user_profile: {ids}"
    assert user_b["id"] not in ids


# ---------------------------------------------------------------------------
# Unauthenticated caller: no JWT claims => auth.uid() is NULL => zero rows.
# (The fail-closed property: an anon request reads nothing from owner-scoped tables.)
# ---------------------------------------------------------------------------

def test_unauthenticated_caller_sees_no_owner_rows(rls_db, event_loop):
    conn, user_a, user_b = rls_db

    async def _check():
        async with conn.transaction():
            # role authenticated but NO sub claim -> auth.uid() resolves to NULL.
            await _set_caller(conn, None)
            child_rows = await conn.fetch("select id from public.child_profile")
            activity_rows = await conn.fetch("select id from public.activity_record")
            profile_rows = await conn.fetch("select id from public.user_profile")
            card_rows = await conn.fetch("select id from public.card_record")
        return child_rows, activity_rows, profile_rows, card_rows

    child_rows, activity_rows, profile_rows, card_rows = _run(event_loop, _check())
    assert child_rows == [], "RLS leak: an unauthenticated caller read child_profile rows"
    assert activity_rows == [], "RLS leak: an unauthenticated caller read activity_record rows"
    assert profile_rows == [], "RLS leak: an unauthenticated caller read user_profile rows"
    # The card_record SELECT policy is owner-only too: an anon caller reads no card rows
    # directly (the public card is reached only via the SECURITY DEFINER token function).
    assert card_rows == [], "RLS leak: an unauthenticated caller read card_record rows"
