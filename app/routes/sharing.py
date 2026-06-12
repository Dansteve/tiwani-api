"""v1 Shared-Child sharing routes (share a recipient's Continuity Card with another person).

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the sharing service
(which verifies ownership / membership, records consent, mints / redeems / lists / revokes
through the 0015 substrate + 0016 functions, and reads the capped card), serialize. The
MVP (Docs/FeatureDecisions.md, the Shared-Child REFINE entry): a Coordinator who OWNS a
recipient invites another person, who redeems an email-bound link and can then see ONLY
that recipient's Continuity Card (the visibility CEILING), with first-class recorded
consent, a visible roster, and instant owner-revoke. The user-facing copy is GOVERNED and
returned as a `copy_key`; the api never prints the internal role names.

The routes, by trust:

  OWNER side (the sharing Coordinator; writes are owner-only):
    POST   /api/v1/sharing/invites
        AUTH. Body {recipient_id, email, role?, subject_kind?}. Verifies the recipient is
        the caller's, records the governed consent, mints the email-bound invite, returns
        {invite_id, token, role, expires_at, copy_key, consent_text}. 404 if the recipient
        is not the caller's. 409 if an ADULT share has no recorded adult consent yet.
    POST   /api/v1/sharing/consent
        AUTH. Body {recipient_id}. Records an ADULT recipient's own consent (the adult-share
        precondition). 404 if not the caller's recipient.
    GET    /api/v1/sharing/recipients/{recipient_id}/roster
        AUTH. The visible "who can see [name]'s card" list (active members + pending
        invites). 404 if not the caller's recipient.
    DELETE /api/v1/sharing/recipients/{recipient_id}/members/{membership_id}
        AUTH, owner only. Instantly revokes a person's access (soft-revoke; RLS stops
        resolving next request). 404 if not found / not the caller's.
    DELETE /api/v1/sharing/recipients/{recipient_id}/invites/{invite_id}
        AUTH, owner only. Revokes a PENDING invite before redemption. 404 if not found.

  REDEEM (the invited person, signed in):
    POST   /api/v1/sharing/redeem
        AUTH. Body {token}. Redeems the email-bound token (atomic, email-bound, first-wins)
        and returns which recipient was linked + the first name + the linked-state copy_key.
        400 if the token is unknown / expired / used / revoked / for a different email.

  VIEWER side (the person a recipient was shared with):
    GET    /api/v1/sharing/shared-with-me
        AUTH. Every recipient shared WITH the caller (first-name-only), each with the
        linked-state copy_key. The entry list to the shared card.
    GET    /api/v1/sharing/recipients/{recipient_id}/card
        AUTH. The CAPPED card read (the CEILING): the SAFE Continuity Card content for a
        recipient the caller is an active member of, plus the linked-state copy_key. 404 if
        the caller is not a member OR there is no live card (never the profile).

Registered under /api/v1 in main.py. Writes are owner-only at the DB (the substrate's
owner-gated RPCs + owner-only update policy) AND re-checked in the service; the card read
is membership-gated in SQL (get_recipient_card_for_member). Note the path order: the more
specific /recipients/{id}/roster, /members/{...}, /invites/{...}, /card sit under a
recipient id, so they never collide with /shared-with-me or /redeem.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthedUser, get_current_user
from app.models.sharing import (
    ConsentRecorded,
    InviteCreated,
    InviteShareRequest,
    RecordConsentRequest,
    RedeemInviteRequest,
    RedeemResult,
    RevokeResult,
    Roster,
    SharedCard,
    SharedWithMe,
)
from app.services import sharing as sharing_service

router = APIRouter()


@router.post(
    "/sharing/invites",
    response_model=InviteCreated,
    status_code=status.HTTP_201_CREATED,
)
def invite_to_recipient(
    payload: InviteShareRequest,
    user: AuthedUser = Depends(get_current_user),
) -> InviteCreated:
    """Invite someone to see one of the caller's recipients' Continuity Card (owner only).

    Verifies the recipient belongs to the caller, records the GOVERNED consent (for a child
    the api authors the wording), mints the email-bound, single-use, short-lived invite, and
    returns the token + expiry + the governed invite copy_key + the recorded consent text.
    404 if the recipient is not the caller's. 409 (calm, capacity-framed copy) if an ADULT
    share is attempted with no recorded adult consent yet (the MVP adult block).
    """
    try:
        return sharing_service.invite_viewer(
            user,
            recipient_id=payload.recipient_id,
            email=str(payload.email),
            role=payload.role,
            subject_kind=payload.subject_kind,
        )
    except sharing_service.RecipientNotOwnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found",
        ) from exc
    except sharing_service.AdultConsentRequiredError as exc:
        # 409, mirroring the one-recipient guard tone: a capacity-framed "they need to agree
        # first" state, not an error the user did wrong. The app shows the adult_blocked copy.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person needs to agree to sharing first",
        ) from exc


@router.post("/sharing/consent", response_model=ConsentRecorded)
def record_consent(
    payload: RecordConsentRequest,
    user: AuthedUser = Depends(get_current_user),
) -> ConsentRecorded:
    """Record an ADULT recipient's own consent to sharing (the adult-share precondition).

    Verifies the recipient is the caller's, records the governed adult consent text, and
    returns the consent id + the governed copy. After this, an adult share for the recipient
    is unblocked. 404 if the recipient is not the caller's.
    """
    try:
        return sharing_service.record_adult_consent(user, recipient_id=payload.recipient_id)
    except sharing_service.RecipientNotOwnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found",
        ) from exc


@router.post("/sharing/redeem", response_model=RedeemResult)
def redeem(
    payload: RedeemInviteRequest,
    user: AuthedUser = Depends(get_current_user),
) -> RedeemResult:
    """Redeem an email-bound invite token (the invited person, signed in).

    Atomic, email-bound, first-wins: requires the caller's auth email to match the invite.
    Returns which recipient was linked + its first name + the governed linked-state copy_key.
    400 if the token is unknown, expired, already used, revoked, or for a different email
    (a single friendly status; we do not leak which, to avoid token probing).
    """
    try:
        return sharing_service.redeem_invite(user, token=payload.token)
    except sharing_service.InviteRedeemError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite link is not valid",
        ) from exc


@router.get(
    "/sharing/recipients/{recipient_id}/roster",
    response_model=Roster,
)
def get_roster(
    recipient_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> Roster:
    """The visible 'who can see [name]'s card' roster for one of the caller's recipients.

    Active members + pending invites, each with the role CODE (the app renders its own
    label) and the relevant timestamps, plus the governed title / empty copy keys. An empty
    roster is a 200 (no one invited yet). 404 if the recipient is not the caller's.
    """
    try:
        return sharing_service.roster(user, recipient_id=recipient_id)
    except sharing_service.RecipientNotOwnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found",
        ) from exc


@router.delete(
    "/sharing/recipients/{recipient_id}/members/{membership_id}",
    response_model=RevokeResult,
)
def revoke_member(
    recipient_id: str,
    membership_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> RevokeResult:
    """Instantly revoke a person's access to a recipient's card (owner only).

    Soft-revoke (the audit row is kept); RLS stops resolving for the revoked member on the
    next request. 404 if the recipient is not the caller's, or the membership is not this
    recipient's / not found / already revoked.
    """
    try:
        result = sharing_service.revoke_access(
            user, recipient_id=recipient_id, membership_id=membership_id
        )
    except sharing_service.RecipientNotOwnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found",
        ) from exc
    if not result.revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared access not found",
        )
    return result


@router.delete(
    "/sharing/recipients/{recipient_id}/invites/{invite_id}",
    response_model=RevokeResult,
)
def revoke_pending_invite(
    recipient_id: str,
    invite_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> RevokeResult:
    """Revoke a PENDING invite before it is redeemed (owner only).

    Soft-revoke; after this the redeem RPC refuses the token. 404 if the recipient is not
    the caller's, or the invite is not this recipient's / already redeemed / not found.
    """
    try:
        result = sharing_service.revoke_invite(
            user, recipient_id=recipient_id, invite_id=invite_id
        )
    except sharing_service.RecipientNotOwnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found",
        ) from exc
    if not result.revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found",
        )
    return result


@router.get("/sharing/shared-with-me", response_model=SharedWithMe)
def list_shared_with_me(
    user: AuthedUser = Depends(get_current_user),
) -> SharedWithMe:
    """Every recipient shared WITH the caller (the viewer's entry list).

    The caller's active, non-owner memberships, each with the recipient FIRST name only and
    the governed linked-state copy_key. An empty list is a valid 200.
    """
    return sharing_service.shared_with_me(user)


@router.get(
    "/sharing/recipients/{recipient_id}/card",
    response_model=SharedCard,
)
def read_card_as_member(
    recipient_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> SharedCard:
    """The CAPPED card read for a shared recipient (the visibility CEILING).

    Returns the SAFE Continuity Card content for a recipient the caller is an active member
    of (membership-gated in SQL), plus the governed linked-state copy_key. The viewer never
    receives the raw profile / LCI / alerts. 404 if the caller is not a member of the
    recipient OR there is no live card yet (never the profile).
    """
    card = sharing_service.read_shared_card(user, recipient_id=recipient_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No shared card available",
        )
    return card
