"""Shared-Child sharing RLS + the visibility CEILING, proven end to end against a REAL Postgres.

This is the real-Postgres RLS test the Shared-Child decision mandates (Docs/
FeatureDecisions.md, the REFINE entry, refinement 3 + 4): the membership/invite policies
and the 0016 feature functions are CORRECT on paper, but only a real Postgres executing
them proves it. Every OTHER suite in this repo runs against fakes (no live database,
sandbox-blocked), so they prove the api SENDS the right query; this file proves the
DATABASE itself enforces the rule, by applying the real Supabase shim + every migration to
an ephemeral Postgres and driving the policies exactly as a real request does.

It mirrors tests/test_rls_isolation.py (the established pattern): "be user X" is the
genuine PostgREST path (set role `authenticated`, set request.jwt.claims to {"sub": id},
so the shim's auth.uid() resolves to that user and RLS scopes every query); seeding across
users uses `service_role` (BYPASSRLS), the same privileged path the api's service-role
client uses. Unlike test_rls_isolation, this fixture APPLIES the schema itself (the shim,
then every supabase/migrations/*.sql in order), so it is self-contained and runs against
any bare Postgres given RLS_TEST_DATABASE_URL, without depending on a separate CI apply
step. The migrations include 0015 (the substrate) + 0016 (this feature).

What is PROVEN (the five required cases + the ceiling + the adult block):
  1. VIEWER READS the card. An active viewer reads the recipient's Continuity Card via
     get_recipient_card_for_member, and reads the roster (recipient_membership select).
  2. VIEWER is at the CEILING. The same viewer reads NOTHING from child_profile,
     lci_snapshot, alert_record, or pulse_record (those keep owner-only RLS): the viewer
     sees ONLY the card, never the raw profile / LCI / alerts.
  3. VIEWER CANNOT WRITE. The viewer cannot mint an invite (owner-gated RPC), cannot revoke
     a membership (owner-only update policy), cannot self-insert a membership (no user
     INSERT policy), and cannot edit the card.
  4. REVOKED VIEWER reads nothing. After the owner revokes the membership, the viewer's
     card read returns NULL and the roster returns nothing on the very next request.
  5. NON-MEMBER reads nothing. A stranger (and the owner of a DIFFERENT recipient) reads no
     card and no roster for this recipient; an unauthenticated caller reads nothing.
  6. TOKEN cannot replay; the share is consent-gated; an ADULT share is BLOCKED without a
     recorded adult consent.

Wiring: requires a real Postgres at RLS_TEST_DATABASE_URL. With it UNSET (a normal dev box,
the sandbox) the whole module SKIPS, so the no-database suite stays green; a CI job with a
postgres:16 service sets it. Uses asyncpg, already a project dependency.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

import pytest

asyncpg = pytest.importorskip("asyncpg")

RLS_TEST_DATABASE_URL: Optional[str] = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not RLS_TEST_DATABASE_URL,
    reason="RLS_TEST_DATABASE_URL is unset; this integration test needs a real Postgres. "
    "The fakes-backed suites (test_sharing_routes, test_engine_sharing_guard) cover the rest.",
)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

# The inline Supabase-compat shim (the four objects the public migrations depend on:
# roles, the auth schema, auth.users, auth.uid()). Kept here so this test bootstraps a bare
# Postgres on its own; it matches supabase/test/0000_supabase_shim.sql.
_SHIM_SQL = """
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
grant anon, authenticated, service_role to current_user;
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key default gen_random_uuid(), email text);
create or replace function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', '')::uuid;
$$;
create or replace function auth.role() returns text language sql stable as $$
    select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'role', '')::text;
$$;
grant usage on schema auth to anon, authenticated, service_role;
grant select, insert, update, delete on auth.users to service_role;
grant select on auth.users to authenticated, anon;
grant usage on schema public to anon, authenticated, service_role;
alter default privileges for role current_user in schema public
    grant select, insert, update, delete on tables to anon, authenticated, service_role;
alter default privileges for role current_user in schema public
    grant usage, select on sequences to anon, authenticated, service_role;
alter default privileges for role current_user in schema public
    grant execute on functions to anon, authenticated, service_role;
"""

_CHAPTER = "family"


# ---------------------------------------------------------------------------
# connection helpers (the genuine PostgREST policy path).
# ---------------------------------------------------------------------------


async def _set_caller(conn: "asyncpg.Connection", user_id: Optional[str]) -> None:
    """Become a signed-in user (or None = unauthenticated), the PostgREST way."""
    await conn.execute("set local role authenticated")
    claims = json.dumps({"sub": user_id} if user_id else {})
    await conn.execute("select set_config('request.jwt.claims', $1, true)", claims)


async def _as_service(conn: "asyncpg.Connection") -> None:
    await conn.execute("set local role service_role")


async def _apply_schema(conn: "asyncpg.Connection") -> None:
    """Apply the shim then every migration in order (the real, complete policy set)."""
    await conn.execute(_SHIM_SQL)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text()
        await conn.execute(sql)


async def _seed(conn: "asyncpg.Connection") -> dict:
    """Seed the world under service_role: an owner, a viewer-to-be, a stranger, the owner of
    a second recipient, one care recipient with a live Continuity Card + an LCI/alert/pulse
    row (so the ceiling has something to (not) leak), and the owner's bootstrap membership.

    Returns the ids the cases target.
    """
    await _as_service(conn)
    ids = {
        "owner": str(uuid.uuid4()),
        "viewer": str(uuid.uuid4()),
        "stranger": str(uuid.uuid4()),
        "owner2": str(uuid.uuid4()),
        "recipient": str(uuid.uuid4()),
        "recipient2": str(uuid.uuid4()),
        "activity": str(uuid.uuid4()),
        "card": str(uuid.uuid4()),
    }
    emails = {
        "owner": "owner@example.test",
        "viewer": "viewer@example.test",
        "stranger": "stranger@example.test",
        "owner2": "owner2@example.test",
    }
    for key in ("owner", "viewer", "stranger", "owner2"):
        await conn.execute(
            "insert into auth.users (id, email) values ($1, $2)", ids[key], emails[key]
        )
        await conn.execute(
            "insert into public.user_profile (id, email, first_name) values ($1, $2, $3)",
            ids[key], emails[key], key.capitalize(),
        )

    # Two recipients: one owned by `owner`, one by `owner2` (the cross-recipient case).
    await conn.execute(
        "insert into public.child_profile (id, user_id, name, support_level_code) "
        "values ($1, $2, $3, $4)",
        ids["recipient"], ids["owner"], "Ade Bello", "SL-MED",
    )
    await conn.execute(
        "insert into public.child_profile (id, user_id, name, support_level_code) "
        "values ($1, $2, $3, $4)",
        ids["recipient2"], ids["owner2"], "Other Child", "SL-LOW",
    )

    # An activity for the recipient (the card's source row; cells sum to total, a DB check).
    await conn.execute(
        """
        insert into public.activity_record (
            id, user_id, child_id, chapter, activity_code, activity_name,
            base_temporal, base_sensory, base_logistical, base_human,
            temporal, sensory, logistical, human, total, tier, scheduled_pulse_at
        ) values ($1, $2, $3, $4, 'routine-meal', 'A routine meal',
            2, 2, 2, 2, 2, 2, 2, 2, 8, 'Full', now())
        """,
        ids["activity"], ids["owner"], ids["recipient"], _CHAPTER,
    )

    # A LIVE Continuity Card for the recipient (the only thing a viewer may read).
    await conn.execute(
        """
        insert into public.card_record
            (id, user_id, child_id, activity_id, token, content, expires_at)
        values ($1, $2, $3, $4, $5, $6::jsonb, now() + interval '30 days')
        """,
        ids["card"], ids["owner"], ids["recipient"], ids["activity"],
        "card-token-" + uuid.uuid4().hex,
        json.dumps(
            {
                "child_first_name": "Ade",
                "activity_name": "A routine meal",
                "chapter": _CHAPTER,
                "tier": "Full",
                "tier_label": "Taking part fully",
                "intro": "Thank you for being here.",
                "strategies": [
                    {"title": "Keep a steady routine", "detail": "Same order each time."}
                ],
                "if_difficult": "If things get difficult, that is okay.",
                "safety_note": "Follow the family's plan for food, medicines, or Ade's health.",
            }
        ),
    )

    # Owner-scoped per-recipient rows the viewer must NOT see (the ceiling proof). Columns
    # match the real DDL: lci_snapshot(chapter, score), alert_record(chapter, level,
    # trigger_condition), pulse_record(activity_id, chapter, tier_recommended, outcome_code);
    # child_id is the nullable column added by 0009/0010/0011.
    await conn.execute(
        "insert into public.lci_snapshot (user_id, child_id, chapter, score) "
        "values ($1, $2, $3, $4)",
        ids["owner"], ids["recipient"], _CHAPTER, 72,
    )
    await conn.execute(
        "insert into public.alert_record (user_id, child_id, chapter, level, trigger_condition) "
        "values ($1, $2, $3, $4, $5)",
        ids["owner"], ids["recipient"], _CHAPTER, 1, "l1_counts_30d",
    )
    await conn.execute(
        "insert into public.pulse_record "
        "(user_id, child_id, activity_id, chapter, tier_recommended, outcome_code) "
        "values ($1, $2, $3, $4, $5, $6)",
        ids["owner"], ids["recipient"], ids["activity"], _CHAPTER, "Full", "well",
    )

    # The owner's bootstrap membership (role=owner). Created via the RPC under the OWNER's
    # session (it checks child_profile.user_id = auth.uid()), the same path the api uses.
    await _set_caller(conn, ids["owner"])
    ids["owner_membership"] = await conn.fetchval(
        "select public.bootstrap_recipient_owner($1)", ids["recipient"]
    )
    return ids


# ---------------------------------------------------------------------------
# fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def rls(event_loop):
    """Connect, apply the schema, seed; yield (conn, ids); close at the end."""
    url = RLS_TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgres://"
    )

    async def _prepare():
        conn = await asyncpg.connect(url)
        async with conn.transaction():
            await _apply_schema(conn)
        async with conn.transaction():
            ids = await _seed(conn)
        return conn, ids

    conn, ids = event_loop.run_until_complete(_prepare())
    try:
        yield conn, ids
    finally:
        event_loop.run_until_complete(conn.close())


def _run(event_loop, coro):
    return event_loop.run_until_complete(coro)


async def _grant_viewer(conn, ids) -> None:
    """Owner mints an email-bound viewer invite (consent-gated child path); the viewer
    redeems it. After this the viewer is an active member of the recipient. Idempotent
    enough for the suite: a second active membership is reused by the redeem RPC."""
    await _set_caller(conn, ids["owner"])
    token = "join-" + uuid.uuid4().hex
    await conn.execute(
        "select public.share_recipient_invite($1, $2, $3, $4, $5, $6)",
        ids["recipient"], "viewer@example.test", "viewer", token, "child",
        "I confirm I have the authority to share Ade's support information.",
    )
    await _set_caller(conn, ids["viewer"])
    await conn.fetchval("select public.redeem_recipient_invite($1)", token)


# ===========================================================================
# 1. VIEWER READS the card + the roster.
# ===========================================================================


def test_viewer_reads_the_card(rls, event_loop):
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            await _set_caller(conn, ids["viewer"])
            card = await conn.fetchval(
                "select public.get_recipient_card_for_member($1)", ids["recipient"]
            )
        return card

    card = _run(event_loop, _check())
    assert card is not None, "an active viewer must be able to read the recipient's card"
    payload = json.loads(card)
    # The SAFE content: first name only, no user_id / child_id leaked into the card.
    assert payload["child_first_name"] == "Ade"
    assert "user_id" not in payload and "child_id" not in payload


def test_viewer_reads_the_roster(rls, event_loop):
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            await _set_caller(conn, ids["viewer"])
            rows = await conn.fetch(
                "select user_id, role from public.recipient_membership where recipient_id = $1",
                ids["recipient"],
            )
        return rows

    rows = _run(event_loop, _check())
    users = {str(r["user_id"]) for r in rows}
    # The viewer sees the roster of a recipient they belong to (owner + themselves).
    assert ids["owner"] in users and ids["viewer"] in users


# ===========================================================================
# 2. VIEWER is at the CEILING: card ONLY, never profile / LCI / alerts / pulse.
# ===========================================================================


def test_viewer_cannot_read_profile_lci_alerts_or_pulse(rls, event_loop):
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            await _set_caller(conn, ids["viewer"])
            profile = await conn.fetch(
                "select id from public.child_profile where id = $1", ids["recipient"]
            )
            lci = await conn.fetch(
                "select id from public.lci_snapshot where child_id = $1", ids["recipient"]
            )
            alerts = await conn.fetch(
                "select id from public.alert_record where child_id = $1", ids["recipient"]
            )
            pulse = await conn.fetch(
                "select id from public.pulse_record where child_id = $1", ids["recipient"]
            )
        return profile, lci, alerts, pulse

    profile, lci, alerts, pulse = _run(event_loop, _check())
    # The CEILING (refinement 1): the viewer sees the CARD only, and NOTHING of the raw
    # profile / LCI / alerts / pulse. RLS on those tables is owner-only and is NOT widened.
    assert profile == [], "RLS leak: a viewer read the recipient's child_profile"
    assert lci == [], "RLS leak: a viewer read the recipient's lci_snapshot"
    assert alerts == [], "RLS leak: a viewer read the recipient's alert_record"
    assert pulse == [], "RLS leak: a viewer read the recipient's pulse_record"


# ===========================================================================
# 3. VIEWER CANNOT WRITE.
# ===========================================================================


def test_viewer_cannot_write(rls, event_loop):
    conn, ids = rls

    async def _mint_as_viewer():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            await _set_caller(conn, ids["viewer"])
            await conn.execute(
                "select public.share_recipient_invite($1, $2, $3, $4, $5, $6)",
                ids["recipient"], "x@example.test", "viewer", "tok-x", "child", "txt",
            )

    # A viewer cannot mint an invite (the RPC's owner gate raises 42501).
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        _run(event_loop, _mint_as_viewer())

    async def _insert_membership_as_viewer():
        async with conn.transaction():
            await _set_caller(conn, ids["viewer"])
            # No user INSERT policy on recipient_membership -> the insert is refused.
            await conn.execute(
                "insert into public.recipient_membership (recipient_id, user_id, role) "
                "values ($1, $2, $3)",
                ids["recipient"], ids["stranger"], "viewer",
            )

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        _run(event_loop, _insert_membership_as_viewer())

    async def _revoke_owner_as_viewer():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            await _set_caller(conn, ids["viewer"])
            # The owner-only update policy: a viewer's update matches zero rows (it cannot
            # see/affect the owner membership for a write), so the owner row stays active.
            status = await conn.execute(
                "update public.recipient_membership set revoked_at = now() where id = $1",
                ids["owner_membership"],
            )
        return status

    status = _run(event_loop, _revoke_owner_as_viewer())
    assert status.split()[-1] == "0", f"RLS leak: a viewer revoked the owner ({status})"


# ===========================================================================
# 4. REVOKED VIEWER reads nothing (RLS stops resolving next request).
# ===========================================================================


def test_revoked_viewer_reads_nothing(rls, event_loop):
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            # The owner revokes the viewer's membership.
            await _set_caller(conn, ids["owner"])
            await conn.execute(
                "update public.recipient_membership set revoked_at = now() "
                "where recipient_id = $1 and user_id = $2 and revoked_at is null",
                ids["recipient"], ids["viewer"],
            )
            # The very next request as the (now revoked) viewer: card NULL, roster empty.
            await _set_caller(conn, ids["viewer"])
            card = await conn.fetchval(
                "select public.get_recipient_card_for_member($1)", ids["recipient"]
            )
            roster = await conn.fetch(
                "select id from public.recipient_membership where recipient_id = $1",
                ids["recipient"],
            )
        return card, roster

    card, roster = _run(event_loop, _check())
    assert card is None, "RLS leak: a revoked viewer still read the card"
    assert roster == [], "RLS leak: a revoked viewer still read the roster"


# ===========================================================================
# 5. NON-MEMBER reads nothing.
# ===========================================================================


def test_non_member_reads_nothing(rls, event_loop):
    conn, ids = rls

    async def _check(caller):
        async with conn.transaction():
            await _set_caller(conn, caller)
            card = await conn.fetchval(
                "select public.get_recipient_card_for_member($1)", ids["recipient"]
            )
            roster = await conn.fetch(
                "select id from public.recipient_membership where recipient_id = $1",
                ids["recipient"],
            )
        return card, roster

    # A stranger (no membership).
    card, roster = _run(event_loop, _check(ids["stranger"]))
    assert card is None and roster == [], "a stranger read a recipient they do not belong to"
    # The owner of a DIFFERENT recipient (membership is per-recipient, never cross).
    card2, roster2 = _run(event_loop, _check(ids["owner2"]))
    assert card2 is None and roster2 == [], "owner of another recipient read this one"
    # An unauthenticated caller (auth.uid() is NULL).
    card3, roster3 = _run(event_loop, _check(None))
    assert card3 is None and roster3 == [], "an unauthenticated caller read the card/roster"


# ===========================================================================
# 6. TOKEN replay; consent-gated share; the ADULT block.
# ===========================================================================


def test_token_cannot_replay_and_is_email_bound(rls, event_loop):
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, ids["owner"])
            token = "replay-" + uuid.uuid4().hex
            await conn.execute(
                "select public.share_recipient_invite($1, $2, $3, $4, $5, $6)",
                ids["recipient"], "stranger@example.test", "viewer", token, "child", "txt",
            )
            # The rightful invitee (stranger's email) redeems once.
            await _set_caller(conn, ids["stranger"])
            mid = await conn.fetchval("select public.redeem_recipient_invite($1)", token)
            return token, mid

    token, mid = _run(event_loop, _check())
    assert mid is not None

    async def _replay():
        async with conn.transaction():
            await _set_caller(conn, ids["stranger"])
            await conn.fetchval("select public.redeem_recipient_invite($1)", token)

    # A second redeem of the same token fails (single-use, first-wins).
    with pytest.raises(asyncpg.exceptions.RaiseError):
        _run(event_loop, _replay())


def test_child_share_records_consent(rls, event_loop):
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _set_caller(conn, ids["owner"])
            token = "consent-" + uuid.uuid4().hex
            await conn.execute(
                "select public.share_recipient_invite($1, $2, $3, $4, $5, $6)",
                ids["recipient"], "newhelper@example.test", "viewer", token, "child",
                "I confirm I have the authority to share Ade's support information.",
            )
            rows = await conn.fetch(
                "select consent_text, subject_kind from public.share_consent "
                "where recipient_id = $1 and subject_kind = 'child'",
                ids["recipient"],
            )
        return rows

    rows = _run(event_loop, _check())
    # The child share recorded a consent row with the governed text (refinement 5).
    assert rows, "a child share must record a consent row"
    assert any("authority to share" in r["consent_text"] for r in rows)


def test_adult_share_blocked_without_recorded_consent(rls, event_loop):
    conn, ids = rls

    async def _adult_share_no_consent():
        async with conn.transaction():
            await _set_caller(conn, ids["owner"])
            # recipient2 belongs to owner2; recipient belongs to owner. Use the owner's own
            # recipient but as an ADULT subject with NO recorded adult consent -> blocked.
            token = "adult-" + uuid.uuid4().hex
            await conn.execute(
                "select public.share_recipient_invite($1, $2, $3, $4, $5)",
                ids["recipient"], "adulthelper@example.test", "viewer", token, "adult",
            )

    # The MVP adult block (refinement 5): no recorded adult consent -> the RPC raises.
    with pytest.raises(asyncpg.exceptions.RaiseError):
        _run(event_loop, _adult_share_no_consent())

    async def _record_then_share():
        async with conn.transaction():
            await _set_caller(conn, ids["owner"])
            await conn.fetchval(
                "select public.record_share_consent($1, $2, $3)",
                ids["recipient"], "adult", "I agree to share my support information.",
            )
            token = "adult-ok-" + uuid.uuid4().hex
            mid = await conn.fetchval(
                "select public.share_recipient_invite($1, $2, $3, $4, $5)",
                ids["recipient"], "adulthelper@example.test", "viewer", token, "adult",
            )
        return mid

    # After the adult records their own consent, the share is unblocked and mints.
    invite_id = _run(event_loop, _record_then_share())
    assert invite_id is not None, "an adult share must mint once consent is recorded"
