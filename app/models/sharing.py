"""Shared-Child sharing pydantic schemas (v3): the cross-repo contract for sharing a
care recipient's Continuity Card with another person (Docs/FeatureDecisions.md, the
Shared-Child REFINE entry; HardRules/Api/Modules/Sharing.md).

The MVP (refinement 1): a Coordinator who OWNS a recipient invites another person, who
redeems an email-bound link and can then see ONLY that recipient's Continuity Card (the
visibility CEILING), never the raw profile / LCI / alerts. Consent is first-class
(refinement 5) and recorded; the roster ("who can see [name]") is visible (refinement
6); the owner revokes access instantly (refinement 6). The user-facing copy is governed
(refinement 7) and carries a `copy_key` so the app renders the matching localized string
and NEVER the internal role names.

  - ShareRole: the role an invite grants. Only `viewer` (the MVP) and `editor` (reserved
    for a future co-coordinator) are invitable; `owner` is never invited (owner transfer
    is a separate deliberate action).
  - SubjectKind: whether the recipient is a child (the Coordinator consents as the
    responsible adult) or an adult (D8; must have recorded their own consent first).
  - InviteShareRequest: the POST body to invite someone {recipient_id, email, role?,
    subject_kind?}. For a child the api records the consent text itself (governed copy);
    the client does not author consent wording.
  - InviteCreated: the POST response {invite_id, token, expires_at, copy_key, consent_text}
    so the app can build the email-bound share link and show the governed invite line.
  - RecordConsentRequest / ConsentRecorded: an ADULT recipient records their own consent
    before any adult share (refinement 5, the adult block).
  - RedeemInviteRequest / RedeemResult: the invited person claims the token and learns
    which recipient they were linked to + the governed linked-state copy key.
  - RosterEntry / Roster: the visible "who can see [name]'s card" list (refinement 6),
    members + pending invites, with status; first-name-only, no internal role label
    leaked as user copy (the role CODE is returned for the app to render its own label).
  - SharedRecipient / SharedWithMe: the list a viewer reads of recipients shared WITH
    them (each with the governed linked-state copy key), the entry to read the card.
  - RevokeResult: the instant-revoke confirmation (refinement 6) with the governed copy.

Every governed string returned here passes the sharing guard at build time
(app/engines/sharing/guard.py); the api returns a `copy_key` so the app can localize.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.card import CardContent


class ShareRole(str, Enum):
    """The role a share invite grants (the invitable subset of recipient_membership.role).

    Only `viewer` (read-only, the Shared-Child MVP role) and `editor` (a reserved
    co-coordinator role, not yet surfaced by the MVP UI) can be invited; `owner` is never
    invitable (the substrate column check enforces this too). These are RBAC CODES, not
    user-facing labels: the governed copy never prints "viewer" / "owner" (refinement 7);
    the app maps the code to its own warm label.
    """

    VIEWER = "viewer"
    EDITOR = "editor"


class SubjectKind(str, Enum):
    """Whether the shared recipient is a child or an adult (gates the consent path).

    child: the creating Coordinator consents as the responsible adult (the MVP path; the
           api records the governed child consent text atomically with the invite).
    adult: D8. The api BLOCKS the share for the MVP unless the adult has ALREADY recorded
           their own consent (refinement 5, the adult block).
    """

    CHILD = "child"
    ADULT = "adult"


class InviteShareRequest(BaseModel):
    """POST /api/v1/sharing/invites: invite someone to see a recipient's Continuity Card.

    recipient_id is one of the CALLER's own care recipients (the service verifies
    ownership). email is the address the invite is bound to (single-use, email-bound).
    role defaults to viewer (the MVP). subject_kind defaults to child (the MVP path); an
    adult share requires a prior recorded adult consent or the api returns 409. The client
    does NOT author consent wording: for a child the api records the GOVERNED consent text
    itself (so the recorded consent is the audited, sign-off copy).
    """

    recipient_id: str = Field(..., min_length=1)
    email: EmailStr
    role: ShareRole = ShareRole.VIEWER
    subject_kind: SubjectKind = SubjectKind.CHILD


class InviteCreated(BaseModel):
    """POST /api/v1/sharing/invites response (the owner's view).

    Carries the invite_id (to revoke a pending invite), the opaque token (the app builds
    the email-bound share link from it; it is the link's only secret), the expiry, the
    governed invite copy_key (so the app renders the warm invite line), and the
    consent_text that was RECORDED for this share (so the owner sees exactly what they
    agreed). The invited person never sees this; they redeem the token.
    """

    model_config = ConfigDict(use_enum_values=True)

    invite_id: str
    token: str
    role: ShareRole
    expires_at: datetime
    copy_key: str
    consent_text: str


class RecordConsentRequest(BaseModel):
    """POST /api/v1/sharing/consent: an adult recipient records their OWN consent.

    recipient_id is one of the caller's own recipients. This is the adult-share
    precondition (refinement 5): the api records the governed adult consent text so a
    subsequent adult share is unblocked. The client does not author the wording.
    """

    recipient_id: str = Field(..., min_length=1)


class ConsentRecorded(BaseModel):
    """The recorded-consent response: the consent id, the copy_key, and the stored text."""

    consent_id: str
    copy_key: str
    consent_text: str


class RedeemInviteRequest(BaseModel):
    """POST /api/v1/sharing/redeem: the invited (signed-in) person claims their token.

    token is the opaque secret from the email-bound link. The service requires the
    caller's auth email to match the invite (email-bound) and is atomic + first-wins; a
    used / expired / revoked / wrong-email token is a friendly 4xx.
    """

    token: str = Field(..., min_length=1)


class RedeemResult(BaseModel):
    """The redeem response: which recipient was linked + the governed linked-state copy.

    recipient_id + recipient_first_name let the app land the person on the shared card.
    role is the granted RBAC code (the app renders its own label). copy_key points at the
    governed linked-state line. No clinical data, first-name-only.
    """

    model_config = ConfigDict(use_enum_values=True)

    recipient_id: str
    recipient_first_name: str
    role: ShareRole
    copy_key: str


class RosterStatus(str, Enum):
    """The status of one entry on the 'who can see [name]'s card' roster (refinement 6).

    active : an active membership (the person can currently see the card).
    pending: a minted invite not yet redeemed (and not expired/revoked).
    """

    ACTIVE = "active"
    PENDING = "pending"


class RosterEntry(BaseModel):
    """One row of the visible 'who can see [name]'s card' roster (refinement 6).

    Either an active member or a pending invite. email is shown so the owner recognises
    who they invited (the invited person's address, not PII about the recipient). role is
    the RBAC CODE (the app maps it to a warm label; the api never prints the role name as
    user copy). granted_at / invited_at give the owner context. id is the membership id
    (for an active row, to revoke the access) or the invite id (for a pending row, to
    revoke the invite); kind disambiguates which.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str
    kind: RosterStatus
    email: Optional[str] = None
    role: ShareRole
    status: RosterStatus
    granted_at: Optional[datetime] = None
    invited_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class Roster(BaseModel):
    """GET /api/v1/sharing/recipients/{recipient_id}/roster: the full visible roster.

    The 'who can see [name]'s information' list the board requires (refinement 6):
    recipient_first_name + the governed title copy_key + the entries (active members and
    pending invites). An empty roster is a valid 200 (no one invited yet); the app shows
    the governed empty line (empty_copy_key).
    """

    recipient_id: str
    recipient_first_name: str
    title_copy_key: str
    empty_copy_key: str
    entries: List[RosterEntry]


class SharedRecipient(BaseModel):
    """One recipient that has been shared WITH the caller (the viewer's list entry).

    recipient_id + recipient_first_name (first-name-only, the card's bar) let the app
    offer the shared card. role is the granted RBAC code. copy_key is the governed
    linked-state line. NO clinical data and nothing beyond the first name: a viewer never
    learns the recipient's full profile from this list.
    """

    model_config = ConfigDict(use_enum_values=True)

    recipient_id: str
    recipient_first_name: str
    role: ShareRole
    copy_key: str


class SharedWithMe(BaseModel):
    """GET /api/v1/sharing/shared-with-me: every recipient shared with the caller."""

    recipients: List[SharedRecipient]


class RevokeResult(BaseModel):
    """The instant-revoke confirmation (refinement 6).

    revoked is True when the access/invite was found and revoked (RLS stops resolving on
    the next request). copy_key is the governed confirmation line. A membership/invite the
    caller does not own is a 404 at the route (not this shape).
    """

    revoked: bool
    copy_key: str


class SharedCard(BaseModel):
    """GET /api/v1/sharing/recipients/{recipient_id}/card: the viewer's capped card read.

    The visibility CEILING (refinement 1): the SAFE Continuity Card content (the SAME
    first-name-only, non-clinical CardContent a helper sees), returned to an active member
    ONLY, plus the governed linked-state copy_key. The viewer never receives the raw
    profile / LCI / alerts; this is the only recipient data a viewer can read.
    """

    recipient_id: str
    copy_key: str
    content: CardContent
