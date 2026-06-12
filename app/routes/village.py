"""Village Delegation Hub routes (Docs/FeatureDecisions.md, the Village Hub).

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the village service
(which drives the migration 0017 RPCs, enforces the membership / role gates + the state
machine at the DB, and attaches the governed copy-key), map the typed errors to HTTP
codes, serialize. The Hub is a CLOSED follow-through loop: a Coordinator (the recipient's
owner) posts a specific bounded NEED for ONE care recipient; a village member (an active
recipient_membership of that recipient, migration 0015) CLAIMS it; the owner CONFIRMS; the
claimer marks it DONE, or DROPS it (which AUTO RE-BROADCASTS to the rest of the village).

EVERY route requires auth (get_current_user) and is RLS-scoped through the service; there
is no unauthenticated surface (unlike the Continuity Card token read). A village member is
a REAL account (refinement 4), so they sign in and act attributably.

The routes:
  POST /api/v3/village/consent                  AUTH, owner. Record per-recipient village
                                                consent (the Art. 9 gate). Body
                                                {recipient_id}; the api supplies the
                                                governed consent text. 403 if not the owner.
  POST /api/v3/village/needs                     AUTH, owner. Post a need. Body = the
                                                what/when/where/contact. 403 if not the
                                                owner; 409 if no village consent is on
                                                record for the recipient (route the
                                                Coordinator to consent first).
  GET  /api/v3/village/needs?recipient_id=...    AUTH, member. The broadcast list for a
                                                recipient (MINIMUM VISIBILITY: summary only,
                                                no exact location / contact). 403 if not a
                                                member.
  GET  /api/v3/village/needs/{need_id}           AUTH, member. One need's detail; the exact
                                                location + contact are present ONLY for the
                                                live claimer of this need or the owner
                                                (per-claim whereabouts). 403 / 404 otherwise.
  POST /api/v3/village/needs/{need_id}/claim     AUTH, member. Offer to help (ATOMIC
                                                first-wins). 409 if no longer open.
  POST /api/v3/village/needs/{need_id}/confirm   AUTH, owner. Confirm a claim.
  POST /api/v3/village/needs/{need_id}/done      AUTH, claimer. Mark done (closes the loop).
  POST /api/v3/village/needs/{need_id}/drop      AUTH, claimer. Step back (AUTO RE-BROADCAST).
  POST /api/v3/village/needs/{need_id}/cancel    AUTH, owner. Cancel a need (terminal).
  GET  /api/v3/village/roster?recipient_id=...   AUTH, member. "Who is in [name]'s village".

Registered under /api/v3 in main.py behind the current-user dependency.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.models.village import (
    ConsentRecorded,
    CreateNeedRequest,
    NeedActionResult,
    NeedDetail,
    NeedSummary,
    RecordConsentRequest,
    RosterResponse,
)
from app.services import village as village_service

router = APIRouter()


def _isoformat(value):
    """Serialize an optional datetime to ISO for the RPC params (None stays None)."""
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# error mapping (the service's typed errors -> HTTP)
# ---------------------------------------------------------------------------


def _not_allowed(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


# ---------------------------------------------------------------------------
# consent (the Art. 9 gate)
# ---------------------------------------------------------------------------


@router.post(
    "/village/consent",
    response_model=ConsentRecorded,
    status_code=status.HTTP_201_CREATED,
)
def record_village_consent(
    payload: RecordConsentRequest,
    user: AuthedUser = Depends(get_current_user),
) -> ConsentRecorded:
    """Record the owner's per-recipient village consent (refinement 5; Art. 9).

    The api supplies the GOVERNED consent text (never the client) and stores it verbatim,
    so the record is the exact agreed wording. Owner-only. 403 if the caller is not the
    recipient's owner.
    """
    try:
        return village_service.record_consent(user, recipient_id=payload.recipient_id)
    except village_service.NotOwnerError as exc:
        raise _not_allowed("Only the family owner can record village consent") from exc
    except village_service.NotMemberError as exc:
        raise _not_allowed("Only the family owner can record village consent") from exc


# ---------------------------------------------------------------------------
# needs: post / list / detail
# ---------------------------------------------------------------------------


@router.post(
    "/village/needs",
    response_model=NeedActionResult,
    status_code=status.HTTP_201_CREATED,
)
def post_need(
    payload: CreateNeedRequest,
    user: AuthedUser = Depends(get_current_user),
) -> NeedActionResult:
    """Post a specific, bounded need for one recipient (owner-only, consent-gated).

    403 if the caller is not the recipient's owner. 409 (with an actionable detail) if no
    village consent is on record for the recipient (the app routes to the consent step
    first). On success returns the new need with status open and the warm 'posted'
    copy-key.
    """
    try:
        return village_service.create_need(
            user,
            recipient_id=payload.recipient_id,
            title=payload.title,
            detail=payload.detail,
            location_text=payload.location_text,
            area_label=payload.area_label,
            contact_name=payload.contact_name,
            contact_phone=payload.contact_phone,
            starts_at=_isoformat(payload.starts_at),
            ends_at=_isoformat(payload.ends_at),
        )
    except village_service.ConsentRequiredError as exc:
        raise _conflict(
            "Record consent to share this recipient's information with the village before "
            "posting a need"
        ) from exc
    except village_service.NotOwnerError as exc:
        raise _not_allowed("Only the family owner can post a need") from exc
    except village_service.NotMemberError as exc:
        raise _not_allowed("Only the family owner can post a need") from exc
    except village_service.NeedConflictError as exc:
        raise _conflict(str(exc)) from exc


@router.get("/village/needs", response_model=List[NeedSummary])
def list_needs(
    recipient_id: str = Query(..., description="The care recipient whose needs to list"),
    user: AuthedUser = Depends(get_current_user),
) -> List[NeedSummary]:
    """The member's broadcast list for a recipient (MINIMUM VISIBILITY).

    Returns each non-terminal need as a summary (title, detail, area-level where, the when
    window, the recipient first name, the caller's claim flag), NEVER the exact location or
    contact. 403 if the caller is not a member of the recipient's village.
    """
    try:
        return village_service.list_needs(user, recipient_id=recipient_id)
    except village_service.NotMemberError as exc:
        raise _not_allowed("You are not part of this recipient's village") from exc


@router.get("/village/needs/{need_id}", response_model=NeedDetail)
def get_need(
    need_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> NeedDetail:
    """One need's detail; the exact logistics are CLAIMER-OR-OWNER only (refinement 3).

    The exact location_text + contact_* are present ONLY when the caller is the live
    claimer of this need or the recipient's owner; any other member sees them null. 403 if
    not a member; 404 if the need does not exist or is not visible.
    """
    try:
        return village_service.get_need_detail(user, need_id=need_id)
    except village_service.NotMemberError as exc:
        raise _not_allowed("You are not part of this recipient's village") from exc
    except village_service.NeedNotFoundError as exc:
        raise _not_found("Need not found") from exc


# ---------------------------------------------------------------------------
# needs: the state-change actions
# ---------------------------------------------------------------------------


@router.post("/village/needs/{need_id}/claim", response_model=NeedActionResult)
def claim_need(
    need_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> NeedActionResult:
    """Offer to help with a need (member-only; ATOMIC first-wins).

    409 if the need is no longer open (someone else just claimed it, or it was confirmed /
    done / cancelled). 403 if not a member; 404 if the need does not exist.
    """
    try:
        return village_service.claim_need(user, need_id=need_id)
    except village_service.NotMemberError as exc:
        raise _not_allowed("You are not part of this recipient's village") from exc
    except village_service.NeedNotFoundError as exc:
        raise _not_found("Need not found") from exc
    except village_service.NeedConflictError as exc:
        raise _conflict(str(exc)) from exc


@router.post("/village/needs/{need_id}/confirm", response_model=NeedActionResult)
def confirm_need(
    need_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> NeedActionResult:
    """Confirm a claim on a need (owner-only).

    403 if not the owner; 409 if the need is not in a claimed state; 404 if it does not
    exist.
    """
    try:
        return village_service.confirm_need(user, need_id=need_id)
    except village_service.NotOwnerError as exc:
        raise _not_allowed("Only the family owner can confirm a helper") from exc
    except village_service.NotMemberError as exc:
        raise _not_allowed("Only the family owner can confirm a helper") from exc
    except village_service.NeedNotFoundError as exc:
        raise _not_found("Need not found") from exc
    except village_service.NeedConflictError as exc:
        raise _conflict(str(exc)) from exc


@router.post("/village/needs/{need_id}/done", response_model=NeedActionResult)
def complete_need(
    need_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> NeedActionResult:
    """Mark a need done (the CLAIMER only; closes the loop).

    403 if the caller does not hold the claim; 409 if the need is not in a claimed /
    confirmed state; 404 if it does not exist.
    """
    try:
        return village_service.complete_need(user, need_id=need_id)
    except village_service.NotClaimerError as exc:
        raise _not_allowed("Only the helper who offered can mark this done") from exc
    except village_service.NeedNotFoundError as exc:
        raise _not_found("Need not found") from exc
    except village_service.NeedConflictError as exc:
        raise _conflict(str(exc)) from exc


@router.post("/village/needs/{need_id}/drop", response_model=NeedActionResult)
def drop_need(
    need_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> NeedActionResult:
    """Step back from a claimed need (the CLAIMER only). AUTO RE-BROADCAST.

    Resets the need to open and re-broadcasts to the rest of the village (refinement 1).
    403 if the caller does not hold the claim; 409 if the need is not claimed / confirmed;
    404 if it does not exist.
    """
    try:
        return village_service.drop_need(user, need_id=need_id)
    except village_service.NotClaimerError as exc:
        raise _not_allowed("Only the helper who offered can step back") from exc
    except village_service.NeedNotFoundError as exc:
        raise _not_found("Need not found") from exc
    except village_service.NeedConflictError as exc:
        raise _conflict(str(exc)) from exc


@router.post("/village/needs/{need_id}/cancel", response_model=NeedActionResult)
def cancel_need(
    need_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> NeedActionResult:
    """Cancel a need (owner-only; terminal).

    403 if not the owner; 404 if the need does not exist. Idempotent on an already-terminal
    need.
    """
    try:
        return village_service.cancel_need(user, need_id=need_id)
    except village_service.NotOwnerError as exc:
        raise _not_allowed("Only the family owner can cancel a need") from exc
    except village_service.NotMemberError as exc:
        raise _not_allowed("Only the family owner can cancel a need") from exc
    except village_service.NeedNotFoundError as exc:
        raise _not_found("Need not found") from exc


# ---------------------------------------------------------------------------
# the roster
# ---------------------------------------------------------------------------


@router.get("/village/roster", response_model=RosterResponse)
def get_roster(
    recipient_id: str = Query(..., description="The care recipient whose village to list"),
    user: AuthedUser = Depends(get_current_user),
) -> RosterResponse:
    """The active village for a recipient ("who is in [name]'s village", refinement 5).

    Returns the active members (RLS-scoped: any active member may read the roster). A
    non-member sees an empty roster (RLS returns nothing), which the app treats as "no
    access".
    """
    return village_service.get_roster(user, recipient_id=recipient_id)
