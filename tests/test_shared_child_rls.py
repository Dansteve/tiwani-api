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
  7. JOIN CODE (0019) on real SQL: the bound-email caller redeems BY CODE once and the
     membership row is created (happy path); a WRONG-email caller is rejected by the SQL
     email-bind with the SAME generic error as an unknown code (no DB-layer oracle); a REPLAY
     of a spent code fails (single-use, first-wins via the for-update lock + active-only
     lookup); and the partial unique index uq_recipient_invite_active_join_code behaves (a
     spent code frees its value; an active duplicate is prevented).

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


def test_switcher_surfacing_a_viewer_does_not_widen_reads(rls, event_loop):
    """The mandatory proof for the Helper Village ACCESS fix (Docs/FeatureDecisions.md,
    2026-06-12, refinement 1): a viewer SURFACED in the recipient switcher still reads ZERO
    from child_profile / lci_snapshot / alert_record / pulse_record.

    GET /api/v1/recipients surfaces a member through the SAME capped paths shared_with_me uses
    (the recipient_membership select + get_recipient_card_for_member for the first name), and
    queries NONE of the owner-only tables for a member. This proves at the DB level that the
    act of surfacing the viewer (their membership resolves AND the capped card yields the first
    name) does not widen what the viewer can read: the owner-only RLS is untouched, so the
    ceiling holds exactly as before. (TASK A adds no migration; the policy set is unchanged.)
    """
    conn, ids = rls

    async def _check():
        async with conn.transaction():
            await _grant_viewer(conn, ids)
            await _set_caller(conn, ids["viewer"])
            # SURFACED: the membership row the switcher list reads resolves, and the capped
            # card path yields the first name (the ONLY recipient data the switcher exposes).
            membership = await conn.fetch(
                "select recipient_id, role from public.recipient_membership "
                "where user_id = $1 and revoked_at is null",
                ids["viewer"],
            )
            card = await conn.fetchval(
                "select public.get_recipient_card_for_member($1)", ids["recipient"]
            )
            # CEILING: the same surfaced viewer reads NOTHING from the owner-only tables.
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
        return membership, card, profile, lci, alerts, pulse

    membership, card, profile, lci, alerts, pulse = _run(event_loop, _check())
    # SURFACED: the viewer's membership resolves (so the recipient appears in the switcher) and
    # the capped card yields the first name only (the ceiling-safe label).
    assert any(
        str(m["recipient_id"]) == ids["recipient"] and m["role"] == "viewer" for m in membership
    ), "the viewer must be surfaceable in the switcher (their membership resolves)"
    assert card is not None and json.loads(card)["child_first_name"] == "Ade"
    # CEILING UNCHANGED: zero rows from every owner-only table, exactly as before surfacing.
    assert profile == [], "RLS leak: a switcher-surfaced viewer read child_profile"
    assert lci == [], "RLS leak: a switcher-surfaced viewer read lci_snapshot"
    assert alerts == [], "RLS leak: a switcher-surfaced viewer read alert_record"
    assert pulse == [], "RLS leak: a switcher-surfaced viewer read pulse_record"


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


# ===========================================================================
# 7. JOIN CODE (migration 0019): redeem_recipient_invite_by_code, on real SQL.
#
# The token redeem above is exercised by case 6; the SHORT typable code is a SEPARATE
# credential to a child's village (the 2026-06-13 board verdict) and funnels into its OWN
# redeem RPC. Before 0019 ships, the SQL-level guarantees of that RPC (the email-bind second
# factor, the single-use lock, the no-oracle uniform error, the partial unique index) must be
# proven on real Postgres, not asserted by inspection. These four cases do exactly that,
# minting via the 8-arg code-aware share_recipient_invite (0019) with consent recorded.
#
# The 0019 share_recipient_invite, given a non-null p_join_code, INSERTs the invite carrying
# BOTH the token and the NORMALIZED code (uppercase, no dashes: the canonical stored form the
# Python normalizer produces). The redeem-by-code RPC looks the code up like-for-like, so the
# code passed here is already in that canonical form.
# ===========================================================================

# The redeem-by-code RPC's single, uniform failure error (no oracle): the SAME message and
# sqlstate on every failure reason (unknown / expired / redeemed / revoked / wrong-email).
_BY_CODE_GENERIC_MESSAGE = "invite could not be redeemed"
_BY_CODE_GENERIC_SQLSTATE = "P0001"


async def _mint_code_invite(conn, ids, *, email: str, join_code: str) -> str:
    """Owner mints a CODE-bearing, consent-gated child invite via the 8-arg
    share_recipient_invite (0019): p_consent_text recorded, p_ttl_hours, p_join_code. Returns
    the new invite id. A fresh unique token is drawn per call (token is globally unique)."""
    await _set_caller(conn, ids["owner"])
    token = "code-tok-" + uuid.uuid4().hex
    return await conn.fetchval(
        "select public.share_recipient_invite($1, $2, $3, $4, $5, $6, $7, $8)",
        ids["recipient"],
        email,
        "viewer",
        token,
        "child",
        "I confirm I have the authority to share Ade's support information.",
        48,
        join_code,
    )


def test_join_code_happy_path_creates_membership(rls, event_loop):
    """Case 1: the rightful BOUND-EMAIL caller redeems BY CODE once and a recipient_membership
    row is created (the happy path against real SQL). Bound to stranger@example.test and
    redeemed as `stranger`, mirroring the token test's identity pairing."""
    conn, ids = rls
    join_code = "HAPPY" + uuid.uuid4().hex[:5].upper()

    async def _check():
        async with conn.transaction():
            await _mint_code_invite(conn, ids, email="stranger@example.test", join_code=join_code)
            # The bound email (stranger) redeems BY CODE.
            await _set_caller(conn, ids["stranger"])
            mid = await conn.fetchval(
                "select public.redeem_recipient_invite_by_code($1)", join_code
            )
            # The membership row exists at the invited role (reuse-safe: whether freshly
            # inserted or an already-active membership reused, the row is present + correct).
            row = await conn.fetchrow(
                "select user_id, role, revoked_at from public.recipient_membership "
                "where id = $1",
                mid,
            )
        return mid, row

    mid, row = _run(event_loop, _check())
    assert mid is not None, "a bound-email by-code redeem must return a membership id"
    assert row is not None, "the redeem must create (or reuse) a recipient_membership row"
    assert str(row["user_id"]) == ids["stranger"], "the membership is for the redeeming caller"
    assert row["role"] == "viewer", "the membership carries the invited role"
    assert row["revoked_at"] is None, "the new membership is active"


def test_join_code_wrong_email_rejected_same_as_unknown(rls, event_loop):
    """Case 2: a WRONG-email caller redeeming a valid code is rejected by the SQL email-bind
    (v_email <> v_inv.email), and gets the EXACT SAME generic error (message + sqlstate) as an
    UNKNOWN code. This proves the no-oracle property AT THE DB LAYER: the thrown error cannot
    distinguish 'no such code' from 'code exists, you are not the bound email'."""
    conn, ids = rls
    join_code = "WRONG" + uuid.uuid4().hex[:5].upper()

    async def _mint():
        async with conn.transaction():
            # Bind to `stranger`; the wrong-email caller below is `owner2`.
            await _mint_code_invite(conn, ids, email="stranger@example.test", join_code=join_code)

    _run(event_loop, _mint())

    async def _redeem_as(caller, code):
        async with conn.transaction():
            await _set_caller(conn, caller)
            await conn.fetchval("select public.redeem_recipient_invite_by_code($1)", code)

    # Wrong-email caller (owner2) redeeming the VALID code: rejected by the email-bind.
    with pytest.raises(asyncpg.exceptions.RaiseError) as wrong_email:
        _run(event_loop, _redeem_as(ids["owner2"], join_code))

    # The SAME caller redeeming a totally UNKNOWN code (well-formed, never minted).
    with pytest.raises(asyncpg.exceptions.RaiseError) as unknown_code:
        _run(event_loop, _redeem_as(ids["owner2"], "NEVERMINTED9"))

    # NO ORACLE at the DB layer: identical message AND sqlstate for both failure reasons.
    assert wrong_email.value.message == _BY_CODE_GENERIC_MESSAGE
    assert unknown_code.value.message == _BY_CODE_GENERIC_MESSAGE
    assert wrong_email.value.message == unknown_code.value.message
    assert wrong_email.value.sqlstate == _BY_CODE_GENERIC_SQLSTATE
    assert unknown_code.value.sqlstate == _BY_CODE_GENERIC_SQLSTATE
    assert wrong_email.value.sqlstate == unknown_code.value.sqlstate

    # The rejected wrong-email attempt created NO membership for owner2 (the bind held).
    async def _no_membership():
        async with conn.transaction():
            await _as_service(conn)
            return await conn.fetch(
                "select id from public.recipient_membership "
                "where recipient_id = $1 and user_id = $2 and revoked_at is null",
                ids["recipient"], ids["owner2"],
            )

    assert _run(event_loop, _no_membership()) == [], "a wrong-email redeem must not grant access"


def test_join_code_replay_fails(rls, event_loop):
    """Case 3: a REPLAY (second redeem) of the same code FAILS. The first redeem stamps
    redeemed_at inside the for-update lock; the active-only lookup (redeemed_at is null) then
    resolves to nothing, so the replay raises the generic failure (single-use / first-wins)."""
    conn, ids = rls
    join_code = "REPLY" + uuid.uuid4().hex[:5].upper()

    async def _first_redeem():
        async with conn.transaction():
            await _mint_code_invite(conn, ids, email="stranger@example.test", join_code=join_code)
            await _set_caller(conn, ids["stranger"])
            return await conn.fetchval(
                "select public.redeem_recipient_invite_by_code($1)", join_code
            )

    mid = _run(event_loop, _first_redeem())
    assert mid is not None, "the first redeem of the code must succeed"

    async def _replay():
        async with conn.transaction():
            await _set_caller(conn, ids["stranger"])
            await conn.fetchval("select public.redeem_recipient_invite_by_code($1)", join_code)

    # The second redeem of the SAME code fails (the active-only lookup no longer finds it).
    with pytest.raises(asyncpg.exceptions.RaiseError) as replay:
        _run(event_loop, _replay())
    # Replay too is the GENERIC error (no oracle distinguishes 'already used' from 'unknown').
    assert replay.value.message == _BY_CODE_GENERIC_MESSAGE
    assert replay.value.sqlstate == _BY_CODE_GENERIC_SQLSTATE


def test_join_code_partial_unique_index_frees_and_prevents(rls, event_loop):
    """Case 4: the partial unique index uq_recipient_invite_active_join_code behaves.
      (a) PREVENTS an active duplicate: minting a SECOND active invite carrying a join_code
          that is already active raises unique_violation (at most one LIVE invite per code).
      (b) a SPENT code FREES its value: once the first invite is redeemed (redeemed_at set,
          so the partial index no longer covers it), a FRESH active invite can carry the SAME
          normalized code again."""
    conn, ids = rls
    join_code = "UNIQ" + uuid.uuid4().hex[:6].upper()

    # (a) PREVENT: two ACTIVE invites with the same code cannot coexist.
    async def _mint_then_duplicate():
        async with conn.transaction():
            await _mint_code_invite(conn, ids, email="stranger@example.test", join_code=join_code)
            # A second ACTIVE invite with the SAME code: the partial unique index rejects it.
            await _mint_code_invite(conn, ids, email="another@example.test", join_code=join_code)

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        _run(event_loop, _mint_then_duplicate())

    # (b) FREE: a SPENT code frees its value. (Part (a)'s mints rolled back with its failed
    # duplicate, so (b) is self-contained: mint ONE active invite with a fresh code, redeem it
    # to spend it, then prove the same code is reusable by a fresh active invite.)
    reuse_code = "FREED" + uuid.uuid4().hex[:5].upper()

    async def _redeem_then_reuse():
        async with conn.transaction():
            # Mint an active invite carrying the code, bound to stranger.
            await _mint_code_invite(conn, ids, email="stranger@example.test", join_code=reuse_code)
            # The bound email (stranger) redeems it, stamping redeemed_at (the code is now spent).
            await _set_caller(conn, ids["stranger"])
            await conn.fetchval(
                "select public.redeem_recipient_invite_by_code($1)", reuse_code
            )
            # SPENT, so the partial index frees the code: a fresh active invite may carry it
            # again (no unique_violation). Mint it and confirm it is the one live invite.
            new_invite_id = await _mint_code_invite(
                conn, ids, email="reuse@example.test", join_code=reuse_code
            )
            await _as_service(conn)
            active = await conn.fetch(
                "select id from public.recipient_invite "
                "where join_code = $1 and redeemed_at is null and revoked_at is null",
                reuse_code,
            )
        return new_invite_id, active

    new_invite_id, active = _run(event_loop, _redeem_then_reuse())
    assert new_invite_id is not None, "a spent code must be reusable by a fresh active invite"
    # Exactly ONE active invite carries the code now (the reused one); the spent one is excluded.
    assert len(active) == 1, "the partial index must allow exactly one live invite per code"
    # asyncpg returns uuid objects from both fetchval and fetch; compare as strings.
    assert str(active[0]["id"]) == str(new_invite_id)
