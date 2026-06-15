"""v1 check-in moment route (the carer "A moment for you" read).

Thin HTTP only (HardRules/Api/SETUP.md): resolve the optional coarse tap, call the
checkin engine (which renders the GOVERNED copy + signposts and guards every string),
serialize. The route requires the current-user dependency (401 without a valid bearer
token). It is READ-ONLY and EPHEMERAL: it writes nothing, stores nothing, records no
analytics, and has no service / DB layer because there is nothing to persist.

Registered under /api/v1 in main.py.

THE SAFE SHAPE (ProductReview.md item 9, the psychiatrist board's conditions): an
OPTIONAL, signpost-only acknowledgement of the carer that points to community/statutory
support PLUS a crisis-capable carer route. It never measures or scores the carer; the
optional ?tap= is a COARSE structured choice that only branches the on-screen signposting.

SIGN-OFF GATE (condition 8): this surface MUST NOT be enabled for real users without
psychiatrist + DPO sign-off (Task 12). It is gated behind app/engines/checkin/flag.py
(OFF by default): while disabled, this route returns 404 (the surface does not exist for
users). Flipping CHECKIN_MOMENT_ENABLED on is the deliberate, sign-off-authorised step.

Endpoint:
  GET /api/v1/checkin/moment   the governed acknowledgement + support signposts for the
                               optional tap branch {tap, intro, acknowledgement,
                               signposts, needs_signoff}. 404 while the surface is gated
                               OFF; 422 on an unknown tap value.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.engines.checkin import (
    MomentTap,
    is_checkin_moment_enabled,
    render_moment,
)
from app.models.checkin import MomentResponse, MomentSignpostView

router = APIRouter()

_TAP_QUERY = Query(
    default=MomentTap.NONE,
    description=(
        "The OPTIONAL coarse tap that branches the on-screen signposting: 'none' (the "
        "default, no tap selected), 'okay', 'a_lot', or 'hard'. It is never a mood scale "
        "and never free text; it only selects which governed acknowledgement + support "
        "block is returned. Nothing is stored."
    ),
)


@router.get("/checkin/moment", response_model=MomentResponse)
def get_checkin_moment(
    user: AuthedUser = Depends(get_current_user),
    tap: MomentTap = _TAP_QUERY,
) -> MomentResponse:
    """The carer check-in moment: a governed acknowledgement + support signposts (item 9).

    Returns the always-shown warm intro, the branch-specific honest acknowledgement, and
    the community + crisis-capable signposts for the optional `tap`. The copy is GOVERNED
    and guarded (clinical AND hollow-affirmation words barred at render time); the app
    renders it verbatim. EPHEMERAL: this read stores nothing and feeds nothing (not the
    engine, the LCI, the alerts, or analytics).

    GATED: while the OFF-by-default flag is disabled this is a 404, so the surface does not
    exist for real users until psychiatrist + DPO sign-off enables it (condition 8). An
    unknown tap value is a 422 from the query validation.
    """
    if not is_checkin_moment_enabled():
        # The surface is gated OFF (no sign-off yet): it does not exist for users. A 404
        # (not a 403) so an unauthorised probe cannot even tell the route is there.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    content = render_moment(tap)
    return MomentResponse(
        tap=content.tap.value,
        intro=content.intro,
        acknowledgement=content.acknowledgement,
        signposts=[
            MomentSignpostView(label=s.label, url=s.url) for s in content.signposts
        ],
    )
