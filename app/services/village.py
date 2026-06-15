"""Village Delegation Hub data service (Docs/FeatureDecisions.md, the Village Hub).

The layer between the Village Hub routes and Supabase. The Hub is the SECOND consumer of
the recipient_membership substrate (migration 0015); its own schema + the atomic,
owner/member-gated RPCs are migration 0017. This service drives those RPCs and the
RLS-scoped reads, maps Postgres errors to friendly typed errors, and attaches the governed
COPY-KEY to each action result.

WHY RPCs, not table writes (HardRules/Api/Modules/Village.md, the 0015 discipline): every
WRITE (post / claim / confirm / done / drop / cancel / record-consent) is a SECURITY
DEFINER RPC that checks membership / role FIRST and enforces the state machine + the atomic
first-wins claim at the DB. There is NO user INSERT/UPDATE/DELETE policy on any Hub table,
so a member cannot write the table directly: the service calls the RPC. The two READS that
must SHAPE columns per-caller (the minimum-visibility list, the per-claim detail) also go
through SECURITY DEFINER RPCs (list_village_needs / get_village_need_detail), because a
plain table select would hand a member the whole row including the exact location + contact
(the table select is only the RLS backstop). The roster read is the plain 0015 membership
select (RLS-scoped).

User scoping and RLS: every call runs through get_anon_client(user.access_token), so
PostgREST carries the caller's JWT and the RPCs' auth.uid() + is_child_member checks resolve
the caller; an owner-revoke (0015) stops a member resolving any read on the next request.

The Postgres RPCs raise with deliberate SQLSTATEs, which this service maps:
  28000 not authenticated      -> (never reached: the route already authenticated) 401-ish
  42501 insufficient privilege -> NotOwnerError / NotMemberError / NotClaimerError (the
                                  caller is not allowed; the route maps to 403, or 404 for a
                                  not-found-style invisibility)
  P0002 no_data_found          -> NeedNotFoundError (404)
  P0001 raise_exception        -> NeedConflictError (409: a state conflict, e.g. "no longer
                                  open to claim", "only a claimed need can be confirmed"),
                                  or ConsentRequiredError for the specific consent-gate raise
                                  (the route maps to 409 with a distinct, actionable detail).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from postgrest.exceptions import APIError

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.village import consent_text as governed_consent_text
from app.engines.village import find_prohibited_words, result_copy_key
from app.engines.village import render as render_copy
from app.models.village import (
    ConsentRecorded,
    NeedActionResult,
    NeedDetail,
    NeedStatus,
    NeedSummary,
    RosterResponse,
    VillageMember,
)

RECIPIENT_MEMBERSHIP_TABLE = "recipient_membership"
CHILD_PROFILE_TABLE = "child_profile"

# The RPC names (migration 0017).
RPC_RECORD_CONSENT = "record_village_consent"
RPC_CREATE_NEED = "create_village_need"
RPC_CLAIM_NEED = "claim_village_need"
RPC_CONFIRM_NEED = "confirm_village_need"
RPC_COMPLETE_NEED = "complete_village_need"
RPC_DROP_NEED = "drop_village_need"
RPC_CANCEL_NEED = "cancel_village_need"
RPC_LIST_NEEDS = "list_village_needs"
RPC_NEED_DETAIL = "get_village_need_detail"

# The substring of the consent-gate raise (create_village_need raises this exact message
# with SQLSTATE P0001 when the recipient has no recorded consent), so the service can map
# it to the distinct ConsentRequiredError rather than a generic conflict.
_CONSENT_GATE_MARKER = "village consent not recorded"


# ---------------------------------------------------------------------------
# typed errors (the route maps each to an HTTP status)
# ---------------------------------------------------------------------------


class NotOwnerError(Exception):
    """The caller is not the owner of the recipient (route -> 403)."""


class NotMemberError(Exception):
    """The caller is not a member of the recipient's village (route -> 403)."""


class NotClaimerError(Exception):
    """The caller does not hold the claim on this need (route -> 403)."""


class NeedNotFoundError(Exception):
    """No such need (or it is invisible to the caller) (route -> 404)."""


class NeedConflictError(Exception):
    """The need is not in a state that allows the action (route -> 409).

    e.g. claiming a need that is no longer open, confirming an unclaimed need, dropping a
    done need. The message is the friendly reason.
    """


class ConsentRequiredError(Exception):
    """A need cannot be broadcast: the recipient has no recorded village consent (409).

    The Art. 9 gate (refinement 5): the owner must record per-recipient consent before any
    need is posted. The route maps this to 409 with an actionable detail so the app can
    route the Coordinator to the consent step.
    """


class NeedContentRejectedError(ValueError):
    """The Coordinator's typed need carried wording the Hub will not broadcast (route -> 422).

    The INGRESS guard (the psychiatrist board's input-side requirement, Fix A): a need is
    shown to a WIDE circle of helpers, so a clinical / health detail typed into one of its
    free-text fields must not travel in it. create_need runs find_prohibited_words over the
    free-text fields BEFORE the create RPC and raises this if any prohibited word is found,
    so nothing is stored. Distinct from ProhibitedCopyError (the emit-time governance fault
    over our OWN copy, a loud 500): this is a calm, expected USER-input rejection. It carries
    NO oracle: it never names the matched word and never echoes the typed text.
    """


# ---------------------------------------------------------------------------
# RPC call + error mapping
# ---------------------------------------------------------------------------


def _rpc(user: AuthedUser, fn: str, params: Dict[str, Any]) -> Any:
    """Call a Hub RPC under the caller's RLS session and return the raw .data.

    Maps the deliberate Postgres SQLSTATEs the 0017 RPCs raise to the service's typed
    errors. A 42501 (insufficient privilege) is disambiguated by the action: the caller
    here is mapped generically (the route refines the message per action), and the message
    text carries the specifics. Any other APIError is re-raised (a genuine fault, not a
    user error).
    """
    client = get_anon_client(user.access_token)
    try:
        response = client.rpc(fn, params).execute()
    except APIError as exc:
        _raise_for_api_error(exc)
        raise  # unreachable; _raise_for_api_error always raises for a mapped code
    return getattr(response, "data", None)


def _raise_for_api_error(exc: APIError) -> None:
    """Translate a Postgres RPC APIError into the service's typed error (always raises)."""
    code = getattr(exc, "code", None)
    message = (getattr(exc, "message", None) or "").strip()

    if code == "P0002":
        raise NeedNotFoundError(message or "Need not found")
    if code == "42501":
        # insufficient_privilege: not owner / not member / not the claimer. The message
        # distinguishes; the route surfaces it as 403. Default to NotMemberError when the
        # message is generic.
        lowered = message.lower()
        if "claimer" in lowered:
            raise NotClaimerError(message)
        if "owner" in lowered:
            raise NotOwnerError(message)
        raise NotMemberError(message or "Not allowed")
    if code == "P0001":
        if _CONSENT_GATE_MARKER in message.lower():
            raise ConsentRequiredError(message)
        raise NeedConflictError(message or "That action is not available right now")
    if code == "22023":
        # invalid parameter (e.g. an empty need title): a validation error.
        raise NeedConflictError(message or "Invalid request")
    if code == "28000":
        # not authenticated at the DB: the route already authenticated, so this is a fault.
        raise NeedConflictError(message or "Not authenticated")
    # Anything else is a genuine fault: do not swallow it.
    raise exc


# ---------------------------------------------------------------------------
# consent (the Art. 9 gate)
# ---------------------------------------------------------------------------


def record_consent(user: AuthedUser, *, recipient_id: str) -> ConsentRecorded:
    """Record the owner's per-recipient village consent (refinement 5).

    The api supplies the GOVERNED consent text (never the client), so the stored record is
    the exact agreed wording. Calls record_village_consent (owner-gated, idempotent). The
    text is rendered with the recipient's first name; if the name is unavailable the
    governed neutral fallback is used (the text still reads). Returns the stored text.
    """
    name = _recipient_first_name(user, recipient_id)
    text = governed_consent_text(name=name)
    _rpc(user, RPC_RECORD_CONSENT, {"p_recipient_id": recipient_id, "p_consent_text": text})
    return ConsentRecorded(recipient_id=recipient_id, consent_text=text)


# ---------------------------------------------------------------------------
# needs: post / list / detail
# ---------------------------------------------------------------------------


def create_need(
    user: AuthedUser,
    *,
    recipient_id: str,
    title: str,
    detail: Optional[str],
    location_text: Optional[str],
    area_label: Optional[str],
    contact_name: Optional[str],
    contact_phone: Optional[str],
    starts_at: Optional[str],
    ends_at: Optional[str],
) -> NeedActionResult:
    """Post a need for one recipient (owner-only, consent-gated). Returns the new need.

    Calls create_village_need (owner gate + consent gate + the 'posted' audit event). On
    success returns a NeedActionResult with status open and the warm 'posted' copy-key.
    Raises NotOwnerError (403) / ConsentRequiredError (409) per the RPC's gates, and
    NeedContentRejectedError (422) if the typed free text carries a prohibited word (the
    INGRESS guard, Fix A): the need is broadcast to the whole village, so a clinical / health
    detail in any free-text field is REJECTED here, before the RPC, so nothing is stored.
    """
    _reject_if_content_unsafe(title, detail, location_text, area_label, contact_name)
    need_id = _rpc(
        user,
        RPC_CREATE_NEED,
        {
            "p_recipient_id": recipient_id,
            "p_title": title,
            "p_detail": detail,
            "p_location_text": location_text,
            "p_area_label": area_label,
            "p_contact_name": contact_name,
            "p_contact_phone": contact_phone,
            "p_starts_at": starts_at,
            "p_ends_at": ends_at,
        },
    )
    name = _recipient_first_name(user, recipient_id)
    return _action_result(str(need_id), NeedStatus.OPEN, "posted", name=name)


def _reject_if_content_unsafe(*fields: Optional[str]) -> None:
    """Raise NeedContentRejectedError if any free-text field carries a prohibited word.

    The INGRESS guard (Fix A): run the Village Hub's low-level word check
    (find_prohibited_words: the same governed clinical + surveillance + role-label set the
    emit-time guard owns) over each non-None free-text field a need broadcasts. We use the
    low-level check, NOT assert_clean: assert_clean raises ProhibitedCopyError, an emit-time
    governance fault over our OWN copy (a loud 500); user input that fails is instead a calm,
    expected 422 (NeedContentRejectedError). On the first field that carries any prohibited
    word we raise immediately, with NO oracle: the error never names the matched word and
    never echoes the user's text, so a caller cannot probe the word list field by field.
    """
    for value in fields:
        if value is None:
            continue
        if find_prohibited_words(value):
            raise NeedContentRejectedError()


def list_needs(user: AuthedUser, *, recipient_id: str) -> List[NeedSummary]:
    """The member's broadcast list for a recipient (MINIMUM VISIBILITY, refinement 2 + 3).

    Calls list_village_needs (member-gated; returns only the safe summary per non-terminal
    need: title, detail, area-level where, the when window, the recipient first name, and
    the caller's claim flag, NEVER the exact location or contact). Raises NotMemberError
    (403) if the caller is not in the recipient's village.
    """
    rows = _rpc(user, RPC_LIST_NEEDS, {"p_recipient_id": recipient_id}) or []
    return [_need_summary(row) for row in rows]


def get_need_detail(user: AuthedUser, *, need_id: str) -> NeedDetail:
    """One need's detail; the exact logistics are CLAIMER-OR-OWNER only (refinement 3).

    Calls get_village_need_detail (member-gated to read at all; the exact location_text +
    contact_* are returned by the RPC only when the caller is the live claimer of THIS need
    or the recipient's owner, else null). Raises NotMemberError (403) / NeedNotFoundError
    (404).
    """
    data = _rpc(user, RPC_NEED_DETAIL, {"p_need_id": need_id})
    row = _first_row(data)
    if row is None:
        raise NeedNotFoundError("Need not found")
    return _need_detail(row)


# ---------------------------------------------------------------------------
# needs: the state-change actions (each returns the warm copy-key)
# ---------------------------------------------------------------------------


def claim_need(user: AuthedUser, *, need_id: str) -> NeedActionResult:
    """Claim a need (member-only; ATOMIC first-wins at the DB). Returns claimed + copy-key.

    Calls claim_village_need: a member offers; the conditional UPDATE wins only if the need
    is still open + unclaimed, so a concurrent second claim raises NeedConflictError (409,
    "no longer open to claim"). Raises NotMemberError (403) / NeedNotFoundError (404).
    """
    _rpc(user, RPC_CLAIM_NEED, {"p_need_id": need_id})
    return self_describing_result(user, need_id, "claimed")


def confirm_need(user: AuthedUser, *, need_id: str) -> NeedActionResult:
    """Confirm a claim (owner-only). Returns confirmed + the warm copy-key.

    Calls confirm_village_need (owner gate; only a claimed need confirms). Raises
    NotOwnerError (403) / NeedConflictError (409) / NeedNotFoundError (404).
    """
    _rpc(user, RPC_CONFIRM_NEED, {"p_need_id": need_id})
    return self_describing_result(user, need_id, "confirmed")


def complete_need(user: AuthedUser, *, need_id: str) -> NeedActionResult:
    """Mark a need done (the CLAIMER only; the loop closes). Returns done + the copy-key.

    Calls complete_village_need (claimer gate; a claimed/confirmed need only). After this
    the logistics no longer resolve to the ex-claimer (access expires per-claim,
    refinement 5). Raises NotClaimerError (403) / NeedConflictError (409) /
    NeedNotFoundError (404).
    """
    _rpc(user, RPC_COMPLETE_NEED, {"p_need_id": need_id})
    return self_describing_result(user, need_id, "done")


def drop_need(user: AuthedUser, *, need_id: str) -> NeedActionResult:
    """Step back from a claimed need (the CLAIMER only). AUTO RE-BROADCAST. Returns open.

    Calls drop_village_need: resets the need to open, clears the claim, records BOTH a
    'dropped' and a 're_broadcast' audit event, so the rest of the village sees it again
    (refinement 1, the critical edge). Returns status open + the warm 'dropped' copy-key.
    Raises NotClaimerError (403) / NeedConflictError (409) / NeedNotFoundError (404).
    """
    _rpc(user, RPC_DROP_NEED, {"p_need_id": need_id})
    return self_describing_result(user, need_id, "dropped")


def cancel_need(user: AuthedUser, *, need_id: str) -> NeedActionResult:
    """Cancel a need (owner-only; terminal). Returns cancelled + the warm copy-key.

    Calls cancel_village_need (owner gate; any non-terminal need -> cancelled). Raises
    NotOwnerError (403) / NeedNotFoundError (404).
    """
    _rpc(user, RPC_CANCEL_NEED, {"p_need_id": need_id})
    return self_describing_result(user, need_id, "cancelled")


def self_describing_result(
    user: AuthedUser, need_id: str, action: str
) -> NeedActionResult:
    """Build the action result by reading the need's current status + name back (RLS-scoped).

    After a state-change RPC, read the need detail back through the same RLS-scoped detail
    RPC (the caller is still a member, or the owner) to report the AUTHORITATIVE new status
    and the recipient's first name for the rendered copy. If the read is not visible (an
    unusual revoke-mid-action race), fall back to the action's implied status so the caller
    still gets a coherent result.
    """
    status = _IMPLIED_STATUS.get(action, NeedStatus.OPEN)
    name = ""
    try:
        row = _first_row(_rpc(user, RPC_NEED_DETAIL, {"p_need_id": need_id}))
    except (NotMemberError, NeedNotFoundError):
        row = None
    if row is not None:
        status = NeedStatus(row["status"])
        name = row.get("recipient_first_name", "") or ""
    return _action_result(need_id, status, action, name=name)


# The status each action implies (the fallback when the read-back is not visible).
_IMPLIED_STATUS: Dict[str, NeedStatus] = {
    "posted": NeedStatus.OPEN,
    "claimed": NeedStatus.CLAIMED,
    "confirmed": NeedStatus.CONFIRMED,
    "done": NeedStatus.DONE,
    "dropped": NeedStatus.OPEN,
    "cancelled": NeedStatus.CANCELLED,
}


# ---------------------------------------------------------------------------
# the roster ("who is in [name]'s village")
# ---------------------------------------------------------------------------


def get_roster(user: AuthedUser, *, recipient_id: str) -> RosterResponse:
    """The active village for a recipient (the 0015 membership select, RLS-scoped).

    Reads the active recipient_membership rows for the recipient under the caller's token
    (the 0015 select policy: any active member may read the roster). Returns each as a
    VillageMember (the raw role is carried but the app shows a warm label, never the role
    word). The recipient is named by first name only.
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(RECIPIENT_MEMBERSHIP_TABLE)
        .select("user_id, role, granted_at, revoked_at")
        .eq("recipient_id", recipient_id)
        .is_("revoked_at", "null")
        .order("granted_at", desc=False)
        .execute()
    )
    members = [
        VillageMember(
            user_id=row["user_id"],
            role=row["role"],
            granted_at=row.get("granted_at"),
            is_me=(row["user_id"] == user.id),
        )
        for row in rows
    ]
    return RosterResponse(
        recipient_first_name=_recipient_first_name(user, recipient_id),
        members=members,
    )


# ---------------------------------------------------------------------------
# row -> model shaping + helpers
# ---------------------------------------------------------------------------


def _action_result(
    need_id: str, status: NeedStatus, action: str, *, name: str
) -> NeedActionResult:
    """Assemble a NeedActionResult with the governed copy-key + rendered message."""
    key = result_copy_key(action)
    return NeedActionResult(
        id=need_id,
        status=status,
        copy_key=key,
        message=render_copy(key, name=name),
    )


def _need_summary(row: Dict[str, Any]) -> NeedSummary:
    return NeedSummary(
        id=str(row["id"]),
        status=NeedStatus(row["status"]),
        title=row["title"],
        detail=row.get("detail"),
        area_label=row.get("area_label"),
        starts_at=row.get("starts_at"),
        ends_at=row.get("ends_at"),
        recipient_first_name=row.get("recipient_first_name", "") or "",
        claimed_by_me=bool(row.get("claimed_by_me")),
        is_claimed=bool(row.get("is_claimed")),
    )


def _need_detail(row: Dict[str, Any]) -> NeedDetail:
    return NeedDetail(
        id=str(row["id"]),
        status=NeedStatus(row["status"]),
        title=row["title"],
        detail=row.get("detail"),
        area_label=row.get("area_label"),
        location_text=row.get("location_text"),
        contact_name=row.get("contact_name"),
        contact_phone=row.get("contact_phone"),
        starts_at=row.get("starts_at"),
        ends_at=row.get("ends_at"),
        recipient_first_name=row.get("recipient_first_name", "") or "",
        claimed_by_me=bool(row.get("claimed_by_me")),
        is_claimed=bool(row.get("is_claimed")),
    )


def _recipient_first_name(user: AuthedUser, recipient_id: str) -> str:
    """The recipient's FIRST name (RLS-scoped); "" if not visible.

    Reads child_profile.name under the caller's token (RLS makes a recipient that is not
    the caller's invisible) and reduces it to the first name (the Continuity Card ceiling).
    Used to resolve {name} in the governed copy and to name the roster.
    """
    client = get_anon_client(user.access_token)
    row = _first(
        client.table(CHILD_PROFILE_TABLE)
        .select("name")
        .eq("id", recipient_id)
        .limit(1)
        .execute()
    )
    full = (row or {}).get("name", "") or ""
    return full.split(" ")[0] if full else ""


def _rows(response: Any) -> List[Dict[str, Any]]:
    """The list of rows from a Supabase execute() RESPONSE object (.data normalised)."""
    return _rows_of_data(getattr(response, "data", None))


def _first(response: Any) -> Optional[Dict[str, Any]]:
    """The first row from a Supabase execute() RESPONSE object, or None."""
    rows = _rows(response)
    return rows[0] if rows else None


def _rows_of_data(data: Any) -> List[Dict[str, Any]]:
    """Normalise an already-extracted .data value (the _rpc return) to a list of rows.

    A PostgREST `returns table(...)` RPC yields .data as a list of row dicts; a scalar RPC
    yields a single value. This handles both (and None) so the RPC readers get one shape.
    """
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def _first_row(data: Any) -> Optional[Dict[str, Any]]:
    """The first row of an already-extracted .data value (the _rpc return), or None."""
    rows = _rows_of_data(data)
    return rows[0] if rows else None
