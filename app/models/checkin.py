"""Check-in moment pydantic schemas: the carer "A moment for you" read.

The cross-repo contract for the check-in moment (ProductReview.md item 9, the psychiatrist
board's SAFE shape). The app mirrors MomentResponse field-for-field and renders the api's
VERBATIM governed copy (it authors no moment wording, exactly as it renders alerts); the
api is the authoritative schema and the only source of the copy.

This surface is EPHEMERAL by design: there is NO stored row, NO migration, and NO request
body that carries a feeling. The ONLY input is the optional ?tap= query (a COARSE
structured tap, the psychiatrist's condition 2), and it only selects which governed
acknowledgement + signposting block the response carries. NOTHING is persisted, fed to the
engine / LCI / alerts, or recorded as analytics.

  - MomentSignpostView: one support resource {label, url?}, the SAME shape as the alert
    SignpostView. url is null for a contextual resource (e.g. local carer organisations,
    a GP) or for a phone route the app renders from the label. Never a clinical referral.
  - MomentResponse: the GET /api/v1/checkin/moment response: {tap, intro, acknowledgement,
    signposts, needs_signoff}. intro is the always-shown warm opener; acknowledgement is
    the branch line; signposts are the community + crisis-capable resources. needs_signoff
    is a constant true reminder that this surface is gated on psychiatrist + DPO sign-off.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from typing_extensions import Literal

# The optional coarse tap on the wire: the MomentTap enum values, never a numeric scale.
# "none" is the no-tap default (the moment opened with no selection).
MomentTapCode = Literal["none", "okay", "a_lot", "hard"]


class MomentSignpostView(BaseModel):
    """One support resource attached to a check-in moment (community or crisis-capable).

    label is the display text; url is the resource link or null for a contextual resource
    (a GP, local carer organisations) or a phone route rendered from the label. Both are
    non-clinical (the engine guards every emitted string). Mirrors the alert SignpostView.
    """

    label: str
    url: Optional[str] = None


class MomentResponse(BaseModel):
    """The carer check-in moment as the app renders it (ProductReview.md item 9).

    Mirrored by the app field-for-field. `intro`, `acknowledgement`, and the `signposts`
    are the VERBATIM governed text (the app never paraphrases). `tap` echoes the branch the
    response is for. `needs_signoff` is always true: a standing reminder that this surface
    is gated on psychiatrist + DPO sign-off (the route only serves it when the OFF-by-default
    flag is enabled). Nothing in this response is derived from a stored carer signal: there
    is none.
    """

    model_config = ConfigDict(use_enum_values=True)

    tap: MomentTapCode
    intro: str
    acknowledgement: str
    signposts: List[MomentSignpostView]
    needs_signoff: bool = True
