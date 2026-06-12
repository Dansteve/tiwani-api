"""The Village Hub RLS + state machine, proven at the layer the sandbox allows.

Docs/FeatureDecisions.md (the Village Hub decision) mandates a real-Postgres RLS test for
this feature (refinement 4 + the substrate's "RLS done right"). There is NO live Supabase
in the sandbox (it is blocked; every service test mocks the client for the same reason, and
migrations 0015 + 0017 are PENDING OWNER APPLY so the tables do not exist on any reachable
DB yet). So this file proves the properties in the two ways the sandbox permits, exactly
mirroring tests/test_recipient_membership_rls.py:

  1. STRUCTURE (parse the migration SQL): the substrate the policies + RPCs depend on is
     present and shaped right. village_member_can_see_need is SECURITY DEFINER in the
     NON-exposed tiwani_private schema and delegates to the 0015 is_child_member; the read
     policy is member-gated; there is NO user INSERT/UPDATE/DELETE policy on any Hub table;
     every write RPC is SECURITY DEFINER with an owner / member / claimer gate; the claim is
     an atomic conditional UPDATE (first-wins); the drop RE-OPENS + re-broadcasts; the post
     is consent-gated; the list / detail RPCs shape the logistics per-caller. A regression
     that loosened any of these (added a user write policy, dropped a gate, returned the
     exact location to every member, removed the consent gate) flips an assertion.

  2. SEMANTICS (a faithful executable model of the policies + the state machine): a tiny
     in-process simulator applies the SAME predicates and transitions the migration
     declares (is_child_member at a role threshold, member-only reads, owner/member/claimer
     write gates, the atomic first-wins claim, the drop re-broadcast, the per-claim
     whereabouts reveal, the consent gate) over a two-recipient / multi-member dataset, and
     the required cases are asserted end to end.

When 0015 + 0017 are applied to production this same matrix is what the owner re-runs
against the live DB; the model here is the proof at the code layer in the meantime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    / "0017_village_hub.sql"
)
SQL = MIGRATION.read_text()
SQL_LOW = SQL.lower()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


SQL_NORM = _norm(SQL)


# ===========================================================================
# 1. STRUCTURE: the substrate the RLS + RPCs depend on is present and shaped right.
# ===========================================================================


def test_migration_is_pending_owner_apply_not_auto_applied():
    assert "pending owner apply" in SQL_LOW
    assert not re.search(r"applied to production \d{4}", SQL_LOW), (
        "0017 must be PENDING OWNER APPLY, not stamped as applied"
    )


def test_it_rides_the_0015_substrate_not_a_second_one():
    # The Hub must REUSE 0015's is_child_member, never redefine the membership tables.
    assert "tiwani_private.is_child_member" in SQL_NORM
    assert "create table if not exists public.recipient_membership" not in SQL_NORM
    assert "create table if not exists public.recipient_invite" not in SQL_NORM


def test_the_three_hub_tables_exist():
    assert "create table if not exists public.village_need" in SQL_NORM
    assert "create table if not exists public.village_need_event" in SQL_NORM
    assert "create table if not exists public.recipient_village_consent" in SQL_NORM


def test_a_need_belongs_to_exactly_one_recipient_inheriting_isolation():
    block = _table_block("create table if not exists public.village_need")
    nb = _norm(block)
    # recipient_id -> child_profile (the one recipient; the isolation key).
    assert "recipient_id uuid not null references public.child_profile" in nb
    # The status machine is the closed loop (refinement 1).
    assert "status in ('open', 'claimed', 'confirmed', 'done', 'cancelled')" in nb
    # The logistics columns exist on the row (shaped per-caller by the RPCs).
    for col in ("location_text", "area_label", "contact_name", "contact_phone",
                "starts_at", "ends_at", "claimed_by"):
        assert col in nb, f"village_need is missing column {col}"


def test_need_has_no_tag_lci_alert_or_score_column_minimum_visibility():
    # Refinement 2: the need carries NOTHING beyond the need + logistics. There must be no
    # tag / lci / alert / score column on village_need (the visibility ceiling).
    block = _norm(_table_block("create table if not exists public.village_need"))
    for forbidden in ("tags", "lci", "alert", "score", "support_level"):
        assert forbidden not in block, (
            f"village_need must not carry a {forbidden} column (minimum visibility)"
        )


def test_visibility_helper_is_security_definer_non_exposed_and_delegates_to_0015():
    fn = _function_block("tiwani_private.village_member_can_see_need")
    assert "security definer" in fn
    assert "set search_path = ''" in fn
    # It delegates the membership decision to the 0015 helper at the viewer threshold.
    assert "is_child_member(n.recipient_id, 'viewer')" in fn


def test_need_read_is_member_gated_and_there_is_no_user_write_policy():
    # READ: member-gated select via the visibility helper.
    assert (
        "create policy village_need_select_member on public.village_need for select "
        "using (tiwani_private.village_member_can_see_need(id))" in SQL_NORM
    )
    # WRITE: NO user insert / update / delete policy on village_need (RPC-only writes).
    need_policies = [p for p in _policy_blocks() if "on public.village_need " in p
                     or p.endswith("on public.village_need")]
    for p in need_policies:
        assert "for insert" not in p
        assert "for update" not in p
        assert "for delete" not in p


def test_no_user_write_policy_on_any_hub_table():
    # Across the whole migration: the only POLICIES are SELECT policies. Every write is an
    # RPC. (A `create policy ... for insert/update/delete` anywhere would let a member write
    # directly.) We scan the policy statements specifically, because `for update` also
    # appears legitimately inside RPC bodies as the `SELECT ... FOR UPDATE` row lock, which
    # is NOT a policy.
    for policy in _policy_blocks():
        assert "for select" in policy, f"a non-select policy exists: {policy}"
        assert "for insert" not in policy, f"an INSERT policy exists: {policy}"
        assert "for update" not in policy, f"an UPDATE policy exists: {policy}"
        assert "for delete" not in policy, f"a DELETE policy exists: {policy}"
    # And there are exactly the three SELECT policies (need / event / consent), no more.
    assert len(_policy_blocks()) == 3


def test_event_audit_is_append_only_owner_readable():
    # The audit table exists, is owner-readable, has the transition actions incl. the
    # re_broadcast, and there is no write policy (the RPCs append).
    block = _norm(_table_block("create table if not exists public.village_need_event"))
    actions = "('posted', 'claimed', 'confirmed', 'done', 'dropped', 'cancelled', 're_broadcast')"
    assert f"action in {actions}" in block
    assert (
        "create policy village_need_event_select_owner on public.village_need_event "
        "for select" in SQL_NORM
    )
    assert "is_child_member(n.recipient_id, 'owner')" in SQL_NORM


def test_post_is_owner_gated_and_consent_gated():
    fn = _function_block("public.create_village_need")
    assert "security definer" in fn and "set search_path = ''" in fn
    # Owner gate.
    assert "is_child_member(p_recipient_id, 'owner')" in fn
    # CONSENT gate (Art. 9, refinement 5): refuses without an active consent row.
    assert "recipient_village_consent" in fn
    assert "village consent not recorded" in fn
    # It posts in the open (broadcast) state and audits a 'posted' event.
    assert "'open'" in fn and "'posted'" in fn


def test_claim_rpc_is_atomic_first_wins():
    fn = _function_block("public.claim_village_need")
    assert "security definer" in fn
    # Member gate.
    assert "is_child_member(v_recipient, 'viewer')" in fn
    # ATOMIC first-wins: the conditional UPDATE only transitions an open, unclaimed need.
    assert "set status = 'claimed'" in fn
    assert "where id = p_need_id and status = 'open' and claimed_by is null" in fn
    # It checks the affected row count and refuses if zero (the second claim loses).
    assert "row_count" in fn
    assert "no longer open to claim" in fn


def test_drop_re_opens_and_re_broadcasts():
    fn = _function_block("public.drop_village_need")
    assert "security definer" in fn
    # Claimer gate.
    assert "v_claimer <> v_uid" in fn
    # AUTO RE-BROADCAST: back to open, claim cleared, and BOTH a dropped + re_broadcast event.
    assert "set status = 'open'" in fn
    assert "claimed_by = null" in fn
    assert "'dropped'" in fn and "'re_broadcast'" in fn


def test_confirm_is_owner_gated_done_is_claimer_gated_cancel_is_owner_gated():
    confirm = _function_block("public.confirm_village_need")
    assert "is_child_member(v_recipient, 'owner')" in confirm
    assert "only a claimed need can be confirmed" in confirm

    done = _function_block("public.complete_village_need")
    assert "v_claimer <> v_uid" in done  # the claimer gate
    assert "only the claimer can mark this need done" in done

    cancel = _function_block("public.cancel_village_need")
    assert "is_child_member(v_recipient, 'owner')" in cancel


def test_list_is_minimum_visibility_no_exact_location_or_contact():
    fn = _function_block("public.list_village_needs")
    assert "security definer" in fn
    assert "is_child_member(p_recipient_id, 'viewer')" in fn  # member-gated
    # It returns area_label, NOT the exact location_text or the contact, and only
    # non-terminal needs (the live board).
    assert "n.area_label" in fn
    assert "n.location_text" not in fn, "the list must not return the exact location"
    assert "n.contact_name" not in fn and "n.contact_phone" not in fn
    assert "n.status in ('open', 'claimed', 'confirmed')" in fn
    # First name only (the Card ceiling).
    assert "split_part(c.name, ' ', 1)" in fn


def test_detail_reveals_exact_logistics_only_to_claimer_or_owner():
    fn = _function_block("public.get_village_need_detail")
    assert "security definer" in fn
    assert "is_child_member(v_recipient, 'viewer')" in fn  # member to read at all
    # The full reveal is gated to the LIVE claimer of THIS need OR the owner.
    assert "v_claimer = v_uid" in fn
    assert "is_child_member(v_recipient, 'owner')" in fn
    # The exact location + contact are CASE-gated on v_can_full, else null.
    assert "when v_can_full then n.location_text else null" in fn
    assert "when v_can_full then n.contact_name" in fn
    assert "when v_can_full then n.contact_phone" in fn


def test_consent_record_rpc_is_owner_gated():
    fn = _function_block("public.record_village_consent")
    assert "security definer" in fn and "set search_path = ''" in fn
    assert "is_child_member(p_recipient_id, 'owner')" in fn


def test_write_rpc_grants_are_authenticated_only_not_anon():
    for fn in (
        "public.create_village_need",
        "public.claim_village_need",
        "public.confirm_village_need",
        "public.complete_village_need",
        "public.drop_village_need",
        "public.cancel_village_need",
        "public.record_village_consent",
        "public.list_village_needs",
        "public.get_village_need_detail",
    ):
        assert f"grant execute on function {fn}" in SQL_NORM
        assert "to anon" not in _function_grants(fn), f"{fn} must not be granted to anon"


# ===========================================================================
# Helpers to slice named blocks out of the migration SQL (same as the 0015 test).
# ===========================================================================


def _table_block(create_stmt: str) -> str:
    start = SQL_LOW.find(create_stmt)
    assert start != -1, f"table not found: {create_stmt}"
    m = re.search(r"\n\);", SQL_LOW[start:])
    assert m is not None, f"table {create_stmt} has no line-anchored closing );"
    return SQL_LOW[start : start + m.end()]


def _function_block(qualified_name: str) -> str:
    start = SQL_LOW.find(f"create or replace function {qualified_name.lower()}")
    assert start != -1, f"function {qualified_name} not found in the migration"
    end = SQL_LOW.find("$$;", start)
    assert end != -1, f"function {qualified_name} has no closing $$;"
    return _norm(SQL_LOW[start : end + 3])


def _function_grants(qualified_name: str) -> str:
    end = SQL_LOW.find("$$;", SQL_LOW.find(f"create or replace function {qualified_name.lower()}"))
    tail = SQL_LOW[end : end + 600]
    return _norm(tail)


def _policy_blocks() -> List[str]:
    blocks = []
    for m in re.finditer(r"create policy(.+?);", SQL_LOW, flags=re.DOTALL):
        blocks.append(_norm(m.group(0)))
    return blocks


# ===========================================================================
# 2. SEMANTICS: a faithful executable model of the declared policies + state machine.
#
# This is NOT a second implementation of the feature; it is the RLS + state-machine
# DECISION TABLE the migration declares, made executable so the required cases run end to
# end. Every rule below maps to a named clause in 0017.
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
class Need:
    id: str
    recipient_id: str
    status: str = "open"
    title: str = "Pick up from school"
    location_text: Optional[str] = "123 School Lane, North Leeds"
    area_label: Optional[str] = "North Leeds"
    contact_name: Optional[str] = "Ada"
    contact_phone: Optional[str] = "07000 000000"
    claimed_by: Optional[str] = None


@dataclass
class Consent:
    recipient_id: str
    revoked_at: Optional[datetime] = None


@dataclass
class HubDB:
    """An in-process model that enforces the SAME predicates + transitions 0017 declares."""

    memberships: List[Membership] = field(default_factory=list)
    needs: List[Need] = field(default_factory=list)
    consents: List[Consent] = field(default_factory=list)
    events: List[tuple] = field(default_factory=list)  # (need_id, action, actor)
    recipient_names: Dict[str, str] = field(default_factory=dict)

    # --- tiwani_private.is_child_member (active-only, role threshold) -----------------
    def is_member(self, caller: Optional[str], recipient_id: str, min_role: str) -> bool:
        if caller is None:
            return False
        threshold = ROLE_RANK[min_role]
        return any(
            m.recipient_id == recipient_id
            and m.user_id == caller
            and m.revoked_at is None
            and ROLE_RANK[m.role] >= threshold
            for m in self.memberships
        )

    def _need(self, need_id: str) -> Optional[Need]:
        return next((n for n in self.needs if n.id == need_id), None)

    def _has_active_consent(self, recipient_id: str) -> bool:
        return any(
            c.recipient_id == recipient_id and c.revoked_at is None for c in self.consents
        )

    # --- village_need_select_member (the table select; whole-row, RLS backstop) -------
    def select_need_row(self, caller: Optional[str], need_id: str) -> Optional[Need]:
        n = self._need(need_id)
        if n is None:
            return None
        # village_member_can_see_need delegates to is_child_member at the viewer threshold.
        if not self.is_member(caller, n.recipient_id, "viewer"):
            return None
        return n

    # --- record_village_consent (owner-gated) ----------------------------------------
    def record_consent(self, caller: Optional[str], recipient_id: str) -> None:
        if not self.is_member(caller, recipient_id, "owner"):
            raise PermissionError("not the owner of this recipient")
        if not self._has_active_consent(recipient_id):
            self.consents.append(Consent(recipient_id=recipient_id))

    # --- create_village_need (owner-gated AND consent-gated) -------------------------
    def create_need(self, caller: Optional[str], recipient_id: str, need_id: str,
                    **kw) -> Need:
        if not self.is_member(caller, recipient_id, "owner"):
            raise PermissionError("not the owner of this recipient")
        if not self._has_active_consent(recipient_id):
            raise PermissionError("village consent not recorded for this recipient")
        n = Need(id=need_id, recipient_id=recipient_id, status="open", **kw)
        self.needs.append(n)
        self.events.append((need_id, "posted", caller))
        return n

    # --- claim_village_need (member-gated, ATOMIC first-wins) ------------------------
    def claim_need(self, caller: Optional[str], need_id: str) -> None:
        n = self._need(need_id)
        if n is None:
            raise LookupError("need not found")
        if not self.is_member(caller, n.recipient_id, "viewer"):
            raise PermissionError("not a member of this recipient")
        # The conditional UPDATE: only an open, unclaimed need transitions (first-wins).
        if not (n.status == "open" and n.claimed_by is None):
            raise ValueError("need is no longer open to claim")
        n.status = "claimed"
        n.claimed_by = caller
        self.events.append((need_id, "claimed", caller))

    # --- confirm_village_need (owner-gated) ------------------------------------------
    def confirm_need(self, caller: Optional[str], need_id: str) -> None:
        n = self._need(need_id)
        if n is None:
            raise LookupError("need not found")
        if not self.is_member(caller, n.recipient_id, "owner"):
            raise PermissionError("not the owner of this recipient")
        if n.status == "confirmed":
            return
        if n.status != "claimed":
            raise ValueError("only a claimed need can be confirmed")
        n.status = "confirmed"
        self.events.append((need_id, "confirmed", caller))

    # --- complete_village_need (CLAIMER-gated) ---------------------------------------
    def complete_need(self, caller: Optional[str], need_id: str) -> None:
        n = self._need(need_id)
        if n is None:
            raise LookupError("need not found")
        if n.claimed_by is None or n.claimed_by != caller:
            raise PermissionError("only the claimer can mark this need done")
        if n.status not in ("claimed", "confirmed"):
            raise ValueError("only a claimed or confirmed need can be marked done")
        n.status = "done"
        self.events.append((need_id, "done", caller))

    # --- drop_village_need (CLAIMER-gated, AUTO RE-BROADCAST) -------------------------
    def drop_need(self, caller: Optional[str], need_id: str) -> None:
        n = self._need(need_id)
        if n is None:
            raise LookupError("need not found")
        if n.claimed_by is None or n.claimed_by != caller:
            raise PermissionError("only the claimer can drop this need")
        if n.status not in ("claimed", "confirmed"):
            raise ValueError("only a claimed or confirmed need can be dropped")
        n.status = "open"
        n.claimed_by = None
        self.events.append((need_id, "dropped", caller))
        self.events.append((need_id, "re_broadcast", caller))

    # --- cancel_village_need (owner-gated) -------------------------------------------
    def cancel_need(self, caller: Optional[str], need_id: str) -> None:
        n = self._need(need_id)
        if n is None:
            raise LookupError("need not found")
        if not self.is_member(caller, n.recipient_id, "owner"):
            raise PermissionError("not the owner of this recipient")
        if n.status in ("done", "cancelled"):
            return
        n.status = "cancelled"
        n.claimed_by = None
        self.events.append((need_id, "cancelled", caller))

    # --- list_village_needs (MINIMUM VISIBILITY: summary, no exact location/contact) --
    def list_needs(self, caller: Optional[str], recipient_id: str) -> List[dict]:
        if not self.is_member(caller, recipient_id, "viewer"):
            raise PermissionError("not a member of this recipient")
        out = []
        first_name = self.recipient_names.get(recipient_id, "").split(" ")[0]
        for n in self.needs:
            if n.recipient_id != recipient_id:
                continue
            if n.status not in ("open", "claimed", "confirmed"):
                continue
            out.append(
                {
                    "id": n.id,
                    "status": n.status,
                    "title": n.title,
                    "area_label": n.area_label,  # area only
                    "recipient_first_name": first_name,
                    "claimed_by_me": n.claimed_by == caller,
                    "is_claimed": n.claimed_by is not None,
                    # NOTE: no location_text, no contact_* in the list.
                }
            )
        return out

    # --- get_village_need_detail (per-claim whereabouts reveal) -----------------------
    def need_detail(self, caller: Optional[str], need_id: str) -> dict:
        n = self._need(need_id)
        if n is None:
            raise LookupError("need not found")
        if not self.is_member(caller, n.recipient_id, "viewer"):
            raise PermissionError("not a member of this recipient")
        # FULL logistics only for a LIVE claim (claimed/confirmed) held by the caller, or
        # the owner. A done / cancelled / re-opened need no longer reveals to the
        # ex-claimer (access expires per-claim, refinement 5).
        can_full = (
            n.claimed_by is not None
            and n.claimed_by == caller
            and n.status in ("claimed", "confirmed")
        ) or self.is_member(caller, n.recipient_id, "owner")
        return {
            "id": n.id,
            "status": n.status,
            "title": n.title,
            "area_label": n.area_label,
            "location_text": n.location_text if can_full else None,
            "contact_name": n.contact_name if can_full else None,
            "contact_phone": n.contact_phone if can_full else None,
            "claimed_by_me": n.claimed_by == caller,
            "is_claimed": n.claimed_by is not None,
        }


# --- a two-recipient world: owner OW1 of R1, owner OW2 of R2, two helpers, a stranger --

OW1, OW2 = "owner-1", "owner-2"
HELPER_A = "helper-a"
HELPER_B = "helper-b"
STRANGER = "stranger-1"
R1, R2 = "recip-1", "recip-2"
N1 = "need-1"


@pytest.fixture
def db() -> HubDB:
    d = HubDB(
        memberships=[
            Membership(R1, OW1, "owner"),
            Membership(R2, OW2, "owner"),
            Membership(R1, HELPER_A, "viewer"),
            Membership(R1, HELPER_B, "viewer"),
        ],
        recipient_names={R1: "Sam Taylor", R2: "Ade Smith"},
    )
    # R1 has recorded village consent; a need is posted by the owner.
    d.record_consent(OW1, R1)
    d.create_need(OW1, R1, N1)
    return d


# --- the required cases (Docs/FeatureDecisions.md, the Village Hub refinements) --------


def test_post_requires_consent_first_art9_gate(db):
    # R2 has NO recorded consent: the owner cannot post a need for it (the Art. 9 gate).
    with pytest.raises(PermissionError):
        db.create_need(OW2, R2, "need-r2")
    # After recording consent, the post succeeds.
    db.record_consent(OW2, R2)
    n = db.create_need(OW2, R2, "need-r2")
    assert n.status == "open"


def test_only_the_owner_can_post(db):
    # A helper (member, not owner) cannot post a need, even with consent on record.
    with pytest.raises(PermissionError):
        db.create_need(HELPER_A, R1, "need-x")


def test_member_sees_the_broadcast_but_not_the_exact_location_or_contact(db):
    # A helper of R1 sees the need on the board (minimum visibility) ...
    board = db.list_needs(HELPER_A, R1)
    assert [b["id"] for b in board] == [N1]
    summary = board[0]
    # ... with the area-level where and the first name, but NO exact location / contact.
    assert summary["area_label"] == "North Leeds"
    assert summary["recipient_first_name"] == "Sam"
    assert "location_text" not in summary
    assert "contact_name" not in summary
    # The detail view, for a member who has NOT claimed, also hides the exact logistics.
    detail = db.need_detail(HELPER_A, N1)
    assert detail["location_text"] is None
    assert detail["contact_name"] is None
    assert detail["contact_phone"] is None


def test_non_member_sees_nothing(db):
    # A stranger and OW2 (owner of a DIFFERENT recipient) both see nothing of R1's needs.
    assert db.select_need_row(STRANGER, N1) is None
    assert db.select_need_row(OW2, N1) is None
    with pytest.raises(PermissionError):
        db.list_needs(STRANGER, R1)
    with pytest.raises(PermissionError):
        db.need_detail(OW2, N1)
    # An unauthenticated caller too.
    assert db.select_need_row(None, N1) is None


def test_claim_is_atomic_first_wins(db):
    # Helper A claims the open need; the second claim (Helper B) loses (first-wins).
    db.claim_need(HELPER_A, N1)
    assert db._need(N1).status == "claimed"
    assert db._need(N1).claimed_by == HELPER_A
    with pytest.raises(ValueError):
        db.claim_need(HELPER_B, N1)  # no longer open
    # A non-member cannot claim at all.
    with pytest.raises(PermissionError):
        db.claim_need(STRANGER, N1)


def test_whereabouts_revealed_only_to_the_claimer_for_that_occurrence(db):
    # Before a claim, even the claimant-to-be does not see the exact logistics.
    assert db.need_detail(HELPER_A, N1)["location_text"] is None
    # Helper A claims -> NOW the exact location + contact resolve to A (and only A).
    db.claim_need(HELPER_A, N1)
    a_detail = db.need_detail(HELPER_A, N1)
    assert a_detail["location_text"] == "123 School Lane, North Leeds"
    assert a_detail["contact_name"] == "Ada"
    assert a_detail["contact_phone"] == "07000 000000"
    # Helper B (a member who did NOT claim) still cannot see the exact logistics.
    b_detail = db.need_detail(HELPER_B, N1)
    assert b_detail["location_text"] is None
    assert b_detail["contact_name"] is None
    # The owner can always see them (to coordinate).
    assert db.need_detail(OW1, N1)["location_text"] == "123 School Lane, North Leeds"


def test_access_expires_per_claim_when_done(db):
    # A claims and the owner confirms; A sees the logistics while the claim is live.
    db.claim_need(HELPER_A, N1)
    db.confirm_need(OW1, N1)
    assert db.need_detail(HELPER_A, N1)["location_text"] is not None
    # A marks it done: the claim is no longer live, so the logistics no longer resolve to A
    # (access expires per-claim, refinement 5).
    db.complete_need(HELPER_A, N1)
    assert db._need(N1).status == "done"
    assert db.need_detail(HELPER_A, N1)["location_text"] is None


def test_drop_auto_re_broadcasts_to_the_rest_of_the_village(db):
    # A claims, then drops: the need RE-OPENS and B can now claim it (refinement 1).
    db.claim_need(HELPER_A, N1)
    db.drop_need(HELPER_A, N1)
    assert db._need(N1).status == "open"
    assert db._need(N1).claimed_by is None
    # The audit recorded both the drop and the re_broadcast.
    actions = [a for (nid, a, who) in db.events if nid == N1]
    assert "dropped" in actions and "re_broadcast" in actions
    # The dropped helper's logistics access is gone; B can pick it up.
    assert db.need_detail(HELPER_A, N1)["location_text"] is None
    db.claim_need(HELPER_B, N1)
    assert db._need(N1).claimed_by == HELPER_B
    assert db.need_detail(HELPER_B, N1)["location_text"] is not None


def test_only_the_claimer_can_complete_or_drop(db):
    db.claim_need(HELPER_A, N1)
    # B (a member, but not the claimer) cannot mark done or drop A's claim.
    with pytest.raises(PermissionError):
        db.complete_need(HELPER_B, N1)
    with pytest.raises(PermissionError):
        db.drop_need(HELPER_B, N1)
    # The owner does not "complete" either (the owner cancels); only the claimer completes.
    with pytest.raises(PermissionError):
        db.complete_need(OW1, N1)


def test_only_the_owner_confirms_or_cancels(db):
    db.claim_need(HELPER_A, N1)
    # A helper cannot confirm.
    with pytest.raises(PermissionError):
        db.confirm_need(HELPER_A, N1)
    # A helper cannot cancel.
    with pytest.raises(PermissionError):
        db.cancel_need(HELPER_A, N1)
    # The owner confirms, then cancels.
    db.confirm_need(OW1, N1)
    assert db._need(N1).status == "confirmed"
    db.cancel_need(OW1, N1)
    assert db._need(N1).status == "cancelled"


def test_revoking_a_member_stops_them_seeing_anything_next_request(db):
    # Helper A is in the village and sees the board.
    assert db.list_needs(HELPER_A, R1)
    # The owner revokes A's membership (the 0015 soft-revoke path): on the NEXT read A is no
    # longer an active member, so the visibility helper returns nothing and the RPCs refuse.
    a_row = next(m for m in db.memberships if m.user_id == HELPER_A)
    a_row.revoked_at = NOW
    assert db.select_need_row(HELPER_A, N1) is None
    with pytest.raises(PermissionError):
        db.list_needs(HELPER_A, R1)
    with pytest.raises(PermissionError):
        db.need_detail(HELPER_A, N1)


def test_done_and_cancelled_needs_drop_off_the_live_board(db):
    # A done or cancelled need is terminal and not on the live broadcast list.
    db.claim_need(HELPER_A, N1)
    db.complete_need(HELPER_A, N1)
    assert db.list_needs(HELPER_B, R1) == []  # the done need is gone from the board
