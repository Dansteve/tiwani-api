"""v1 calendar context route (the display-only Real-World Context Layer read).

Thin HTTP only (HardRules/Api/SETUP.md): resolve the optional date range, call the pure
context builder (which renders the GOVERNED copy + guards every string), serialize. The
route requires the current-user dependency (401 without a valid bearer token). It reads NO
user data: the calendar is PUBLIC reference data (UK bank holidays + England school
holidays), so there is no service / DB layer and no RLS surface, and it touches NO score
(the determinism firewall keeps these dates out of the LCE/LCI/Alerts).

Registered under /api/v1 in main.py.

THE SAFE SHAPE (FeatureDecisions.md 2026-06-19, the Part B conditions): the app overlays
these public dates on the check-in history it already has, so a Coordinator can SEE a quiet
stretch fell over (say) the holidays and judge it for themselves. WORLD-FACTS only,
symmetric (selected by date, blind to any score), non-causal.

SIGN-OFF GATE: this surface MUST NOT be enabled for real users without the Task-12
psychiatrist sign-off on the governed copy. It is gated behind app/engines/context/flag.py
(OFF by default): while disabled, this route returns 404 (the surface does not exist for
users). Flipping CALENDAR_CONTEXT_ENABLED on is the deliberate, sign-off-authorised step.

Endpoint:
  GET /api/v1/context/calendar   the governed public calendar windows overlapping the
                                 resolved [from, to] range {from_date, to_date, intro,
                                 hedge, windows, needs_signoff}. 404 while the surface is
                                 gated OFF; 422 on an unparseable date.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.engines.context import build_calendar_context, is_calendar_context_enabled
from app.models.context import CalendarContextResponse, CalendarWindowView

router = APIRouter()

_FROM_QUERY = Query(
    default=None,
    alias="from",
    description=(
        "Optional ISO start date (YYYY-MM-DD) for the context window. Defaults to about "
        "18 months before `to`. The span is clamped server-side, so the read is always "
        "bounded."
    ),
)
_TO_QUERY = Query(
    default=None,
    description="Optional ISO end date (YYYY-MM-DD). Defaults to today.",
)


@router.get("/context/calendar", response_model=CalendarContextResponse)
def get_calendar_context(
    user: AuthedUser = Depends(get_current_user),
    from_: Optional[date] = _FROM_QUERY,
    to: Optional[date] = _TO_QUERY,
) -> CalendarContextResponse:
    """Public calendar context overlapping the resolved date range (Part B, calendar slice).

    Returns the governed intro + hedge and the public UK calendar windows (bank holidays,
    school holidays) that overlap the resolved [from_date, to_date] range, in date order,
    each with its world-fact note + provenance. The copy is GOVERNED and guarded (clinical
    AND editorialising / causal words barred at render time); the app renders it verbatim
    and overlays the windows on the check-in history. It reads no user data and touches no
    score.

    GATED: while the OFF-by-default flag is disabled this is a 404, so the surface does not
    exist for real users until the psychiatrist copy sign-off enables it. An unparseable
    date is a 422 from the query validation.
    """
    if not is_calendar_context_enabled():
        # The surface is gated OFF (no sign-off yet): it does not exist for users. A 404
        # (not a 403) so an unauthorised probe cannot even tell the route is there.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    context = build_calendar_context(date.today(), from_, to)
    return CalendarContextResponse(
        from_date=context.from_date,
        to_date=context.to_date,
        intro=context.intro,
        hedge=context.hedge,
        windows=[
            CalendarWindowView(
                kind=rendered.window.kind,
                label=rendered.window.label,
                start=rendered.window.start,
                end=rendered.window.end,
                division=rendered.window.division,
                note=rendered.note,
                source=rendered.window.source,
                confidence=rendered.window.confidence,
            )
            for rendered in context.windows
        ],
    )
