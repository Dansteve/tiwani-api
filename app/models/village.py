"""Village Delegation Hub pydantic schemas (Docs/FeatureDecisions.md, the Village Hub).

The cross-repo contract for the Village Hub endpoints (HardRules/Api/Modules/Village.md).
The Hub is a closed follow-through loop: a Coordinator (the recipient's owner) posts a
specific, bounded NEED for one care recipient; a village member (an active
recipient_membership of that recipient, migration 0015) CLAIMS it; the owner CONFIRMS; the
claimer marks it DONE, or DROPS it (which auto re-broadcasts). The schemas are shaped to
the MINIMUM-VISIBILITY rule (refinement 2) and the per-claim whereabouts rule (refinement
3): the broadcast list and the detail view carry only the need + logistics, never the
recipient's tags / LCI / alerts / score, and the exact location + contact are present only
on the claimer-or-owner detail view.

  - NeedStatus: the status machine (open / claimed / confirmed / done / cancelled).
  - CreateNeedRequest: the POST /api/v1/village/needs body (what / when / where / contact).
  - NeedSummary: one row of the member's broadcast list. Carries the title, detail, the
    WHEN window, an AREA-level where (never the exact place), the status, the recipient's
    FIRST name, and whether the CALLER holds the claim. NO contact, NO exact location: the
    list is minimum-visibility (refinement 2 + 3).
  - NeedDetail: the single-need view. Same fields as NeedSummary PLUS the exact
    location_text + contact_name + contact_phone, which are populated ONLY when the caller
    is the live claimer of this need or the recipient's owner (the api returns them null
    for any other member; the SECURITY DEFINER detail RPC enforces this server-side).
  - NeedActionResult: the response to claim / confirm / done / drop / cancel: the need id,
    the new status, and the warm governed COPY-KEY the app shows (the copy-key contract).
  - RecordConsentRequest / ConsentRecorded: the per-recipient Art. 9 consent gate. The api
    returns the verbatim governed consent text it stored.
  - VillageMember / RosterResponse: the "who is in [name]'s village" roster (the active
    recipient_membership rows for a recipient), owner-facing.

The user-facing copy keys these models reference are GOVERNED (app/engines/village/copy.py):
warm, capacity-framed, non-clinical, non-surveillance, no internal role labels.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class NeedStatus(str, Enum):
    """The Village need status machine (migration 0017).

    open is the broadcast / re-broadcast state; claimed once a member offers; confirmed
    once the owner confirms; done once the claimer completes; cancelled if the owner
    withdraws it. A drop is not a status: it resets a claimed/confirmed need to open (the
    auto re-broadcast).
    """

    OPEN = "open"
    CLAIMED = "claimed"
    CONFIRMED = "confirmed"
    DONE = "done"
    CANCELLED = "cancelled"


class CreateNeedRequest(BaseModel):
    """The POST /api/v1/village/needs body: a specific, bounded ask (refinement 1).

    recipient_id is the ONE care recipient the need is for (the owner must own it, and the
    recipient must have a recorded village consent, both enforced by the create RPC).
    title is the WHAT (required; specific offers convert). detail is an optional fuller
    description. location_text is the exact WHERE-to-the-task (revealed per-claim only);
    area_label is the coarser area the broadcast list may show the roster. contact_name /
    contact_phone are the WHO-to-reach on the day (revealed per-claim only). starts_at /
    ends_at are the bounded WHEN window.
    """

    recipient_id: str
    title: str = Field(min_length=1, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=2000)
    location_text: Optional[str] = Field(default=None, max_length=500)
    area_label: Optional[str] = Field(default=None, max_length=120)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_phone: Optional[str] = Field(default=None, max_length=40)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class NeedSummary(BaseModel):
    """One row of the member's broadcast list (MINIMUM VISIBILITY, refinement 2 + 3).

    What a village member sees on the board: the need's id and status, the WHAT (title +
    detail), an AREA-level where (area_label only, never the exact location_text), the WHEN
    window, the recipient's FIRST name (the Continuity Card ceiling), whether the CALLER
    holds the claim, and whether anyone does. It deliberately carries NO contact and NO
    exact location: those are per-claim (NeedDetail).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    status: NeedStatus
    title: str
    detail: Optional[str] = None
    area_label: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    recipient_first_name: str
    claimed_by_me: bool
    is_claimed: bool


class NeedDetail(BaseModel):
    """The single-need view; the exact logistics are CLAIMER-OR-OWNER ONLY (refinement 3).

    Everything in NeedSummary, plus location_text / contact_name / contact_phone, which the
    api populates ONLY when the caller is the live claimer of THIS need or the recipient's
    owner (any other member gets them as null). This is the per-claim, occurrence-scoped
    whereabouts reveal: the exact where + who-to-contact is shown to exactly the one member
    actually doing the task, for that one need, and disappears when the need is done or
    dropped (the claim is no longer live). The SECURITY DEFINER detail RPC nulls these
    server-side; this model simply carries them.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    status: NeedStatus
    title: str
    detail: Optional[str] = None
    area_label: Optional[str] = None
    location_text: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    recipient_first_name: str
    claimed_by_me: bool
    is_claimed: bool


class NeedActionResult(BaseModel):
    """The response to a need state change (claim / confirm / done / drop / cancel).

    id is the need; status is the new status after the action; copy_key is the STABLE
    governed copy-key (app/engines/village/copy.py) the app shows as the warm confirmation
    (the copy-key contract: the app renders the key, the api never hand-writes the copy in
    the route). message is the rendered governed text for that key (with the recipient's
    first name resolved), provided so a thin client can show it without its own copy table.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    status: NeedStatus
    copy_key: str
    message: str


class RecordConsentRequest(BaseModel):
    """The POST /api/v1/village/consent body: record per-recipient village consent.

    recipient_id is the recipient the owner is recording consent for (Art. 9, refinement
    5). The consent TEXT is the governed text (app/engines/village/copy.py), supplied by
    the api, not the client, so the record is the exact agreed wording; the client only
    names the recipient.
    """

    recipient_id: str


class ConsentRecorded(BaseModel):
    """The record-consent response: the stored consent text + when (the audit echo).

    recipient_id is the recipient; consent_text is the verbatim governed text stored; the
    app shows it back as the confirmation of what was agreed.
    """

    model_config = ConfigDict(frozen=True)

    recipient_id: str
    consent_text: str


class VillageMember(BaseModel):
    """One active member of a recipient's village (a recipient_membership row, 0015).

    user_id is the member's account; granted_at is when they joined the village. role is
    carried for the api but the app NEVER shows the raw role word (the governed copy bars
    "viewer" / "owner" as user-facing labels); the app renders a warm human label. is_me
    flags the caller's own row.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    role: str
    granted_at: Optional[datetime] = None
    is_me: bool = False


class RosterResponse(BaseModel):
    """The "who is in [name]'s village" roster for a recipient (refinement 5).

    recipient_first_name names the recipient (first name only). members is the active
    village. It is owner-facing (the roster select policy is owner-gated in 0015 for the
    invite side; the membership select is any-member, so the app gates the management
    surface to the owner).
    """

    model_config = ConfigDict(frozen=True)

    recipient_first_name: str
    members: List[VillageMember]
