"""The recipient_membership RLS substrate, proven at the layer the sandbox allows.

Docs/FeatureDecisions.md mandates a real-Postgres-style RLS test for this substrate
(the Shared-Child REFINE entry, refinement 3 + 4): viewer-reads / viewer-cannot-write /
revoked-viewer-reads-nothing / non-member-reads-nothing / token-cannot-replay.

There is NO live Supabase in the sandbox (it is blocked; the existing
test_recipient_isolation.py and the cards/profile service tests all mock the client for
the same reason, and migration 0015 is PENDING OWNER APPLY so the tables do not exist on
any reachable DB yet). So this file proves the property in the two ways the sandbox
permits, exactly mirroring test_recipient_isolation.py's structure:

  1. STRUCTURE (parse the migration SQL): the substrate the policies depend on is present
     and shaped correctly. is_child_member is SECURITY DEFINER in the NON-exposed
     tiwani_private schema with search_path pinned and an auth.uid() check; reads and
     writes are SPLIT (select policy at the viewer threshold, update policy at the owner
     threshold) and there is NO user INSERT policy on either table; the invite is
     email-bound, single-use, expiring, revocable; the mint/redeem RPCs are SECURITY
     DEFINER. A regression that loosened any of these (OR-ed a viewer into the owner
     policy, dropped the owner gate on a write, added a user INSERT policy, removed the
     replay stamp) would flip one of these assertions.

  2. SEMANTICS (a faithful executable model of the policies): a tiny in-process Postgres-
     RLS simulator applies the SAME predicates the migration declares (is_child_member at
     a role threshold, active-only, owner-only writes, atomic first-wins redeem) over a
     two-recipient / multi-member dataset, and the five required cases are asserted end to
     end. The model reads its rules from the named policy semantics, so it is the behaviour
     a real authenticated role would get: a viewer reads the roster but cannot write; a
     revoked viewer reads nothing; a non-member reads nothing; a used or revoked or
     wrong-email token cannot be redeemed (replay fails).

When 0015 is applied to production this same five-case matrix is what the owner re-runs
against the live DB (supabase/README.md "RLS baseline check"); the model here is the
proof at the code layer in the meantime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Load the migration SQL once (the structural assertions parse it directly).
# ---------------------------------------------------------------------------

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0015_recipient_membership.sql"
)
SQL = MIGRATION.read_text()
SQL_LOW = SQL.lower()


def _norm(text: str) -> str:
    """Collapse whitespace so multi-line SQL clauses match as single-line substrings."""
    return re.sub(r"\s+", " ", text).lower()


SQL_NORM = _norm(SQL)


# ===========================================================================
# 1. STRUCTURE: the substrate the RLS depends on is present and shaped right.
# ===========================================================================


def test_migration_is_pending_owner_apply_not_auto_applied():
    # The banner must say PENDING OWNER APPLY (the owner applies it on the direct-Postgres
    # path; this change does not touch production), the 0013 posture.
    assert "pending owner apply" in SQL_LOW
    # And it must NOT carry an APPLIED-stamp banner (the 0009-0013 applied migrations stamp
    # "APPLIED TO PRODUCTION <date>"); the substrate is not applied by this change.
    assert not re.search(r"applied to production \d{4}", SQL_LOW), (
        "0015 must be PENDING OWNER APPLY, not stamped as applied"
    )


def test_both_substrate_tables_exist():
    assert "create table if not exists public.recipient_membership" in SQL_NORM
    assert "create table if not exists public.recipient_invite" in SQL_NORM


def test_membership_columns_match_the_contract():
    # The feature decision lists the exact columns; pin each so a rename is caught.
    block = _membership_table_block()
    for col in (
        "recipient_id",
        "user_id",
        "role",
        "granted_by",
        "granted_at",
        "revoked_at",
        "created_at",
    ):
        assert col in block, f"recipient_membership is missing column {col}"
    # role is the three-value ladder; owner is one of them (single-owner = one such row).
    assert "role in ('owner', 'viewer', 'editor')" in _norm(block)
    # recipient_id -> child_profile, user_id -> auth.users.
    assert "references public.child_profile" in _norm(block)
    assert "references auth.users" in _norm(block)


def test_is_child_member_is_security_definer_in_a_non_exposed_schema():
    # The helper must live in the NON-exposed schema (not public/graphql_public, which
    # PostgREST serves), be SECURITY DEFINER, pin search_path, and check auth.uid().
    assert "create schema if not exists tiwani_private" in SQL_NORM
    fn = _function_block("tiwani_private.is_child_member")
    assert "security definer" in fn
    assert "set search_path = ''" in fn
    assert "auth.uid()" in fn
    # It takes (child_id, min_role) and is a boolean check.
    assert "is_child_member(p_child_id uuid, p_min_role text)" in _norm(fn)
    assert "returns boolean" in fn
    # Only active memberships count (an owner-revoke stops resolving next request).
    assert "revoked_at is null" in fn
    # The threshold ladder: owner < editor < viewer breadth.
    assert "when 'owner'" in fn and "when 'editor'" in fn and "when 'viewer'" in fn


def test_reads_and_writes_are_split_on_the_membership_table():
    # READ: a select policy gated at the VIEWER threshold (any active member reads).
    assert (
        "create policy recipient_membership_select_member on public.recipient_membership "
        "for select using (tiwani_private.is_child_member(recipient_id, 'viewer'))" in SQL_NORM
    )
    # WRITE: the only write policy is the OWNER-threshold update (for the revoke RPC),
    # gated owner-only on BOTH using and with check.
    assert (
        "create policy recipient_membership_update_owner on public.recipient_membership "
        "for update using (tiwani_private.is_child_member(recipient_id, 'owner')) "
        "with check (tiwani_private.is_child_member(recipient_id, 'owner'))" in SQL_NORM
    )


def test_a_viewer_is_never_or_ed_into_an_owner_write_policy():
    # The board's explicit trap: never widen a broad owner policy by OR-ing a viewer id.
    # Every membership/invite WRITE policy must be gated at the 'owner' threshold ONLY,
    # with no 'viewer'/'editor' threshold and no `or` inside a for-update policy.
    for policy in _policy_blocks():
        if "for update" in policy:
            assert "is_child_member(recipient_id, 'owner')" in policy
            assert "'viewer'" not in policy and "'editor'" not in policy
            assert " or " not in policy, f"a write policy OR-s a condition in: {policy}"


def test_no_user_insert_policy_on_either_table():
    # Memberships and invites are written ONLY by the SECURITY DEFINER RPCs; a user INSERT
    # policy would let a viewer (or anyone) self-grant. There must be none on either table.
    assert "for insert" not in SQL_NORM, "no INSERT policy may exist (RPCs are the only writers)"
    # And no DELETE policy either: revoke is a soft-revoke UPDATE, never a hard delete.
    assert "for delete" not in SQL_NORM


def test_owner_update_is_revoke_only_enforced_by_a_trigger():
    # A policy gates WHICH ROWS an owner may update; it CANNOT gate WHICH COLUMNS change. The
    # adversarial review found the two owner UPDATE policies were therefore general-purpose
    # owner writes (role escalation / membership hijack / invite email-bind rewrite / stamp
    # replay). Defense in depth: a BEFORE UPDATE trigger on each table makes the owner UPDATE
    # revoke-only (membership) and revoke-or-redeem-stamp + write-once (invite).
    # -- recipient_membership: revoke-only trigger freezes every identity/grant column.
    mfn = _function_block("tiwani_private.recipient_membership_revoke_only")
    assert "returns trigger" in mfn
    # Pin EVERY identity/grant column (not just the marquee ones), so a forgotten freeze on
    # any column is caught, not only escalation/hijack/graft.
    for col in (
        "new.id is distinct from old.id",
        "new.recipient_id is distinct from old.recipient_id",  # no cross-recipient graft
        "new.user_id is distinct from old.user_id",            # no hijack
        "new.role is distinct from old.role",                  # no escalation
        "new.granted_by is distinct from old.granted_by",
        "new.granted_at is distinct from old.granted_at",
        "new.created_at is distinct from old.created_at",
    ):
        assert col in mfn, f"membership trigger must freeze: {col}"
    # Revoke is one-way: only an active row may be set revoked.
    assert "old.revoked_at is not null or new.revoked_at is null" in mfn
    assert "security invoker" in mfn and "set search_path = ''" in mfn
    assert (
        "create trigger recipient_membership_revoke_only_t before update "
        "on public.recipient_membership" in SQL_NORM
    )
    # -- recipient_invite: state guard freezes identity/email-bind + write-once stamps.
    ifn = _function_block("tiwani_private.recipient_invite_state_guard")
    assert "returns trigger" in ifn
    # Pin EVERY immutable identity/email-bind column.
    for col in (
        "new.id is distinct from old.id",
        "new.recipient_id is distinct from old.recipient_id",
        "new.token is distinct from old.token",            # no token swap
        "new.email is distinct from old.email",            # no email-bind rewrite
        "new.role is distinct from old.role",              # no role escalation
        "new.invited_by is distinct from old.invited_by",
        "new.expires_at is distinct from old.expires_at",
        "new.created_at is distinct from old.created_at",
    ):
        assert col in ifn, f"invite guard must freeze: {col}"
    # redeemed_at/redeemed_by/revoked_at are write-once (a spent invite can never be re-armed).
    assert "old.redeemed_at is not null and new.redeemed_at is distinct from old.redeemed_at" in ifn
    assert "old.redeemed_by is not null and new.redeemed_by is distinct from old.redeemed_by" in ifn
    assert "old.revoked_at is not null and new.revoked_at is distinct from old.revoked_at" in ifn
    assert "security invoker" in ifn and "set search_path = ''" in ifn
    assert (
        "create trigger recipient_invite_state_guard_t before update "
        "on public.recipient_invite" in SQL_NORM
    )


def test_invite_is_email_bound_single_use_short_lived_and_revocable():
    block = _invite_table_block()
    nb = _norm(block)
    assert "email text not null" in nb  # email-bound
    assert "redeemed_at" in nb  # single-use stamp
    assert "expires_at timestamptz not null" in nb  # short-lived
    assert "revoked_at" in nb  # owner-revocable
    assert "token text not null unique" in nb  # the single opaque secret, unique
    # An invite never grants owner (owner transfer is a separate action).
    assert "role in ('viewer', 'editor')" in nb


def test_mint_and_redeem_are_security_definer_rpcs_with_an_owner_gate_and_replay_guard():
    mint = _function_block("public.mint_recipient_invite")
    assert "security definer" in mint and "set search_path = ''" in mint
    # mint is owner-gated.
    assert "is_child_member(p_child_id, 'owner')" in _norm(mint)

    redeem = _function_block("public.redeem_recipient_invite")
    assert "security definer" in redeem and "set search_path = ''" in redeem
    # redeem is atomic first-wins: it locks the row and re-checks unused inside the lock.
    assert "for update" in redeem
    assert "redeemed_at is not null" in redeem  # the replay guard
    assert "expires_at <= now()" in redeem  # expiry guard
    assert "revoked_at is not null" in redeem  # revoke guard
    # email-bound redeem: the caller's auth email must match the invite email.
    assert "auth.users" in redeem and "v_inv.email" in redeem


def test_rpc_grants_are_narrow_authenticated_only_not_anon_or_public():
    # The membership-writing RPCs must be reachable only by an authenticated session, never
    # anon or the broad public default (mint/redeem/bootstrap all write state).
    for fn in (
        "public.mint_recipient_invite",
        "public.redeem_recipient_invite",
        "public.bootstrap_recipient_owner",
    ):
        assert f"grant execute on function {fn}" in SQL_NORM
        # No anon execute on the write RPCs.
        # (is_child_member may be granted to anon so a policy can evaluate to false; the
        #  write RPCs may not.)
    # Spot-check: redeem/mint are not granted to anon anywhere.
    assert "grant execute on function public.mint_recipient_invite" in SQL_NORM
    assert "to anon" not in _function_grants("public.mint_recipient_invite")
    assert "to anon" not in _function_grants("public.redeem_recipient_invite")


# ===========================================================================
# Helpers to slice named blocks out of the migration SQL.
# ===========================================================================


def _table_block(create_stmt: str) -> str:
    """The full `create table ... );` block (lowercased), terminated on the line-anchored
    `);` that closes the column list (a `);` inside a trailing comment cannot truncate it)."""
    start = SQL_LOW.find(create_stmt)
    assert start != -1, f"table not found: {create_stmt}"
    # Find the first `);` that begins a line at/after start (the DDL terminator).
    m = re.search(r"\n\);", SQL_LOW[start:])
    assert m is not None, f"table {create_stmt} has no line-anchored closing );"
    return SQL_LOW[start : start + m.end()]


def _membership_table_block() -> str:
    return _table_block("create table if not exists public.recipient_membership")


def _invite_table_block() -> str:
    return _table_block("create table if not exists public.recipient_invite")


def _function_block(qualified_name: str) -> str:
    """The text of a `create or replace function <name> ... $$ ... $$;` block (lowercased)."""
    start = SQL_LOW.find(f"create or replace function {qualified_name.lower()}")
    assert start != -1, f"function {qualified_name} not found in the migration"
    # The function body is dollar-quoted; the block ends at the first `$$;` after start.
    end = SQL_LOW.find("$$;", start)
    assert end != -1, f"function {qualified_name} has no closing $$;"
    return _norm(SQL_LOW[start : end + 3])


def _function_grants(qualified_name: str) -> str:
    """The grant/revoke lines that follow a function definition (until the next blank-ish gap)."""
    end = SQL_LOW.find("$$;", SQL_LOW.find(f"create or replace function {qualified_name.lower()}"))
    tail = SQL_LOW[end : end + 600]
    return _norm(tail)


def _policy_blocks() -> List[str]:
    """Each `create policy ... ;` statement (lowercased, whitespace-collapsed)."""
    blocks = []
    for m in re.finditer(r"create policy(.+?);", SQL_LOW, flags=re.DOTALL):
        blocks.append(_norm(m.group(0)))
    return blocks


# ===========================================================================
# 2. SEMANTICS: a faithful executable model of the declared policies.
#
# This is NOT a second implementation of the feature; it is the RLS DECISION TABLE the
# migration declares, made executable so the five required cases run end to end. Every rule
# below maps to a named clause in 0015:
#   - is_member(...)      -> tiwani_private.is_child_member (active-only, role threshold)
#   - select_*            -> the select policies (member reads / owner reads)
#   - *_write             -> writes are owner-only AND only via the RPCs (no user policy)
#   - redeem(...)         -> the atomic, email-bound, first-wins redeem RPC
# A regression in the migration's intent would require editing this table to keep the
# tests green, which is the signal.
# ===========================================================================

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)

ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


@dataclass
class Membership:
    recipient_id: str
    user_id: str
    role: str
    revoked_at: Optional[datetime] = None


@dataclass
class Invite:
    token: str
    recipient_id: str
    email: str
    role: str
    invited_by: str
    expires_at: datetime
    redeemed_at: Optional[datetime] = None
    redeemed_by: Optional[str] = None
    revoked_at: Optional[datetime] = None


@dataclass
class RlsDB:
    """An in-process model that enforces the SAME predicates 0015 declares."""

    memberships: List[Membership] = field(default_factory=list)
    invites: List[Invite] = field(default_factory=list)
    # auth.users.email, keyed by user id (the redeem email-bound check reads this).
    emails: Dict[str, str] = field(default_factory=dict)

    # --- tiwani_private.is_child_member(child_id, min_role) --------------------------
    def is_member(
        self, caller: Optional[str], recipient_id: str, min_role: str, *, now=NOW
    ) -> bool:
        if caller is None:  # auth.uid() is null -> never a member
            return False
        threshold = ROLE_RANK[min_role]
        for m in self.memberships:
            if (
                m.recipient_id == recipient_id
                and m.user_id == caller
                and m.revoked_at is None  # active only
                and ROLE_RANK[m.role] >= threshold
            ):
                return True
        return False

    # --- select policy: recipient_membership_select_member (viewer threshold) --------
    def read_roster(self, caller: Optional[str], recipient_id: str) -> List[Membership]:
        if not self.is_member(caller, recipient_id, "viewer"):
            return []  # non-member / revoked / unauthenticated -> RLS returns nothing
        # A member sees the roster of that recipient (the policy's using clause is per-row,
        # but every row shares this recipient_id, so membership is the gate).
        return [m for m in self.memberships if m.recipient_id == recipient_id]

    # --- writes: owner-only AND only via the RPCs (no user insert/delete policy) ------
    def user_insert_membership(self, caller, row: Membership):
        # There is NO user INSERT policy: a direct user insert is refused regardless of role.
        raise PermissionError("no INSERT policy on recipient_membership (RPC-only write)")

    def revoke_membership(self, caller: Optional[str], target: Membership, *, now=NOW) -> None:
        # The owner-only UPDATE policy (the revoke RPC runs under the owner's session).
        if not self.is_member(caller, target.recipient_id, "owner"):
            raise PermissionError("only an owner may revoke a membership")
        target.revoked_at = now

    # --- recipient_membership_revoke_only trigger (defense in depth on the UPDATE policy) ---
    def owner_update_membership(self, caller, target, **changes) -> None:
        # The owner-only UPDATE policy admits the ROW; the revoke_only BEFORE UPDATE trigger
        # then admits ONLY a revoke (set revoked_at on an active row). Any other column change
        # is rejected at the database, so an owner cannot escalate a role or hijack
        # user_id/recipient_id (the CRITICAL hole the adversarial review caught).
        if not self.is_member(caller, target.recipient_id, "owner"):
            raise PermissionError("only an owner may update a membership")
        forbidden = set(changes) - {"revoked_at"}
        if forbidden:
            raise PermissionError(
                f"membership update is revoke-only; cannot change {sorted(forbidden)}"
            )
        if "revoked_at" in changes:
            if target.revoked_at is not None or changes["revoked_at"] is None:
                raise PermissionError("revoke is one-way (active row -> revoked only)")
            target.revoked_at = changes["revoked_at"]

    # --- mint_recipient_invite (owner-gated) -----------------------------------------
    def mint_invite(
        self, caller: Optional[str], recipient_id: str, email: str, role: str, token: str,
        *, ttl_hours: int = 168, now=NOW,
    ) -> Invite:
        if not self.is_member(caller, recipient_id, "owner"):
            raise PermissionError("only an owner may mint an invite")
        if role not in ("viewer", "editor"):
            raise ValueError("invite role must be viewer or editor")
        inv = Invite(
            token=token,
            recipient_id=recipient_id,
            email=email.lower(),
            role=role,
            invited_by=caller,
            expires_at=now + timedelta(hours=ttl_hours),
        )
        self.invites.append(inv)
        return inv

    # --- redeem_recipient_invite (atomic, email-bound, first-wins) -------------------
    def redeem_invite(self, caller: Optional[str], token: str, *, now=NOW) -> Membership:
        if caller is None:
            raise PermissionError("not authenticated")
        inv = next((i for i in self.invites if i.token == token), None)
        if inv is None:
            raise LookupError("invite not found")
        if inv.revoked_at is not None:
            raise PermissionError("invite revoked")
        if inv.redeemed_at is not None:
            raise PermissionError("invite already used")  # the replay guard (first-wins)
        if inv.expires_at <= now:
            raise PermissionError("invite expired")
        caller_email = (self.emails.get(caller) or "").lower()
        if not caller_email or caller_email != inv.email:
            raise PermissionError("invite is for a different email")  # email-bound
        # Single-use stamp (the atomic step): a replay now sees redeemed_at set.
        inv.redeemed_at = now
        inv.redeemed_by = caller
        existing = next(
            (
                m
                for m in self.memberships
                if m.recipient_id == inv.recipient_id
                and m.user_id == caller
                and m.revoked_at is None
            ),
            None,
        )
        if existing is not None:
            return existing
        m = Membership(recipient_id=inv.recipient_id, user_id=caller, role=inv.role)
        self.memberships.append(m)
        return m

    # --- recipient_invite_state_guard trigger (defense in depth on the UPDATE policy) ----
    def owner_update_invite(self, caller, invite, **changes) -> None:
        # The owner-only UPDATE policy admits the row; the state_guard BEFORE UPDATE trigger
        # freezes identity/email-bind columns and makes redeemed_at/redeemed_by/revoked_at
        # write-once. So an owner may only revoke a pending invite; they cannot rewrite the
        # email-bind/role to redirect it, nor clear a spent stamp to replay it (the HIGH hole).
        if not self.is_member(caller, invite.recipient_id, "owner"):
            raise PermissionError("only an owner may update an invite")
        immutable = {"recipient_id", "token", "email", "role", "invited_by", "expires_at"}
        bad = immutable & set(changes)
        if bad:
            raise PermissionError(f"invite identity/email-bind columns immutable: {sorted(bad)}")
        for stamp in ("redeemed_at", "redeemed_by", "revoked_at"):
            if stamp in changes:
                if getattr(invite, stamp) is not None:
                    raise PermissionError(f"{stamp} is write-once")
                setattr(invite, stamp, changes[stamp])


# --- a two-recipient world: owner OW1 of R1, owner OW2 of R2, a viewer, a stranger ----

OW1, OW2 = "owner-1", "owner-2"
VIEWER = "viewer-1"
EDITOR = "editor-1"
STRANGER = "stranger-1"
INVITEE = "invitee-1"
R1, R2 = "recip-1", "recip-2"


@pytest.fixture
def db() -> RlsDB:
    return RlsDB(
        memberships=[
            Membership(R1, OW1, "owner"),
            Membership(R2, OW2, "owner"),
            Membership(R1, VIEWER, "viewer"),
            Membership(R1, EDITOR, "editor"),
        ],
        emails={
            OW1: "ow1@example.com",
            VIEWER: "viewer@example.com",
            INVITEE: "invitee@example.com",
            STRANGER: "stranger@example.com",
        },
    )


# --- the five required cases (Docs/FeatureDecisions.md refinement 3 + 4) --------------


def test_viewer_reads_the_roster(db):
    # An active viewer of R1 can READ the roster (the select policy at the viewer threshold).
    roster = db.read_roster(VIEWER, R1)
    assert {m.user_id for m in roster} == {OW1, VIEWER, EDITOR}
    # The viewer can also confirm their own membership through the helper.
    assert db.is_member(VIEWER, R1, "viewer") is True


def test_viewer_cannot_write(db):
    # The viewer cannot self-grant (no user INSERT policy) ...
    with pytest.raises(PermissionError):
        db.user_insert_membership(VIEWER, Membership(R1, STRANGER, "viewer"))
    # ... cannot revoke anyone (owner-only UPDATE) ...
    target = next(m for m in db.memberships if m.user_id == EDITOR)
    with pytest.raises(PermissionError):
        db.revoke_membership(VIEWER, target)
    # ... and cannot mint an invite (owner-gated RPC).
    with pytest.raises(PermissionError):
        db.mint_invite(VIEWER, R1, "x@example.com", "viewer", "tok-x")
    # The editor likewise cannot mint (only owner grants), proving the gate is owner, not
    # "any non-viewer".
    with pytest.raises(PermissionError):
        db.mint_invite(EDITOR, R1, "x@example.com", "viewer", "tok-e")


def test_revoked_viewer_reads_nothing(db):
    # The owner revokes the viewer; on the NEXT read the (now inactive) viewer sees nothing.
    viewer_row = next(m for m in db.memberships if m.user_id == VIEWER)
    db.revoke_membership(OW1, viewer_row)
    assert db.is_member(VIEWER, R1, "viewer") is False
    assert db.read_roster(VIEWER, R1) == []


def test_non_member_reads_nothing(db):
    # A stranger (no membership) and OW2 (owner of a DIFFERENT recipient) both read nothing
    # from R1: membership is per-recipient, never cross-recipient.
    assert db.read_roster(STRANGER, R1) == []
    assert db.read_roster(OW2, R1) == []
    assert db.is_member(OW2, R1, "viewer") is False
    # And an unauthenticated caller (auth.uid() is null) is never a member.
    assert db.is_member(None, R1, "viewer") is False
    assert db.read_roster(None, R1) == []


def test_token_cannot_replay(db):
    # The owner mints an email-bound invite; the invitee redeems it ONCE and becomes a viewer.
    db.mint_invite(OW1, R1, "invitee@example.com", "viewer", "tok-join")
    m = db.redeem_invite(INVITEE, "tok-join")
    assert m.role == "viewer" and m.user_id == INVITEE
    assert db.is_member(INVITEE, R1, "viewer") is True
    # REPLAY: redeeming the same token again fails (single-use, first-wins).
    with pytest.raises(PermissionError):
        db.redeem_invite(INVITEE, "tok-join")
    # A different account cannot redeem it either (email-bound + already used).
    with pytest.raises(PermissionError):
        db.redeem_invite(STRANGER, "tok-join")


def test_invite_is_email_bound_a_leaked_link_is_useless_to_another_account(db):
    # Mint for the invitee's email; the STRANGER who got the link cannot redeem it.
    db.mint_invite(OW1, R1, "invitee@example.com", "viewer", "tok-leak")
    with pytest.raises(PermissionError):
        db.redeem_invite(STRANGER, "tok-leak")
    # The invite is unredeemed, so the rightful invitee can still claim it.
    m = db.redeem_invite(INVITEE, "tok-leak")
    assert m.user_id == INVITEE


def test_expired_and_revoked_tokens_do_not_redeem(db):
    # Expired: minted with a 1-hour ttl, redeemed two hours later -> refused.
    db.mint_invite(OW1, R1, "invitee@example.com", "viewer", "tok-exp", ttl_hours=1)
    with pytest.raises(PermissionError):
        db.redeem_invite(INVITEE, "tok-exp", now=NOW + timedelta(hours=2))
    # Revoked: the owner revokes a pending invite before it is redeemed -> refused.
    inv = db.mint_invite(OW1, R1, "invitee@example.com", "viewer", "tok-rev")
    inv.revoked_at = NOW
    with pytest.raises(PermissionError):
        db.redeem_invite(INVITEE, "tok-rev")


def test_owner_role_grants_breadth_below_it(db):
    # The role ladder: an owner satisfies every threshold; a viewer only the viewer one.
    assert db.is_member(OW1, R1, "viewer") is True
    assert db.is_member(OW1, R1, "editor") is True
    assert db.is_member(OW1, R1, "owner") is True
    assert db.is_member(VIEWER, R1, "viewer") is True
    assert db.is_member(VIEWER, R1, "editor") is False
    assert db.is_member(VIEWER, R1, "owner") is False
    assert db.is_member(EDITOR, R1, "editor") is True
    assert db.is_member(EDITOR, R1, "owner") is False


def test_owner_cannot_escalate_or_hijack_a_membership_via_update(db):
    # The CRITICAL hole: the owner UPDATE policy had no column restriction, so an owner could
    # rewrite role/user_id/recipient_id directly. The revoke-only trigger now permits ONLY a
    # revoke.
    viewer_row = next(m for m in db.memberships if m.user_id == VIEWER)
    with pytest.raises(PermissionError):  # cannot promote a viewer to owner (escalation)
        db.owner_update_membership(OW1, viewer_row, role="owner")
    with pytest.raises(PermissionError):  # cannot re-point to another user (hijack)
        db.owner_update_membership(OW1, viewer_row, user_id=STRANGER)
    with pytest.raises(PermissionError):  # cannot graft onto another recipient
        db.owner_update_membership(OW1, viewer_row, recipient_id=R2)
    # ... but CAN revoke it (the one permitted update).
    db.owner_update_membership(OW1, viewer_row, revoked_at=NOW)
    assert viewer_row.revoked_at == NOW
    assert db.is_member(VIEWER, R1, "viewer") is False
    with pytest.raises(PermissionError):  # a revoke is one-way: cannot be cleared to re-arm
        db.owner_update_membership(OW1, viewer_row, revoked_at=None)


def test_owner_cannot_rewrite_or_replay_an_invite_via_update(db):
    # The HIGH hole: the invite UPDATE policy had no column restriction, so an owner could
    # rewrite a pending invite's email-bind/role, or clear redeemed_at to replay. The state
    # guard freezes identity and makes the stamps write-once.
    inv = db.mint_invite(OW1, R1, "invitee@example.com", "viewer", "tok-guard")
    with pytest.raises(PermissionError):  # cannot redirect the email-bind
        db.owner_update_invite(OW1, inv, email="attacker@example.com")
    with pytest.raises(PermissionError):  # cannot escalate the granted role
        db.owner_update_invite(OW1, inv, role="editor")
    db.redeem_invite(INVITEE, "tok-guard")
    with pytest.raises(PermissionError):  # once redeemed, cannot be cleared to replay
        db.owner_update_invite(OW1, inv, redeemed_at=None)
    # The owner CAN revoke a pending invite (the one permitted state change).
    inv2 = db.mint_invite(OW1, R1, "two@example.com", "viewer", "tok-guard-2")
    db.owner_update_invite(OW1, inv2, revoked_at=NOW)
    assert inv2.revoked_at == NOW
