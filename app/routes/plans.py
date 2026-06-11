"""v3 Preparation Plan routes (the Life Continuity Engine endpoints).

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the plans
service (which runs the engine and stores the record), serialize. All routes
require the current-user dependency (401 without a valid bearer token); the plan
write is user-scoped through the service with Supabase RLS as the backstop.

Registered under /api/v3 in main.py, alongside the other v3 routes. The engine is
server-side and deterministic; the app renders the returned plan and never
recomputes a score (Product.md section 4.4, the LCE-is-server-side rule).

The two GET reads return STORED values and never re-run the engine (the LCE is run
only on the POST): GET /api/v3/plans lists the caller's stored plans as summaries, and
GET /api/v3/plans/{activity_id} returns one stored plan in the PreparationPlan shape.
Both are RLS-scoped to the caller; a non-owned activity_id is a 404 (it is invisible
under RLS, and the api does not confirm it exists for anyone).

Endpoints:
  POST /api/v3/plans                        run the LCE for the caller's care
                                            recipient + the chosen activity; store
                                            the activity_record; return the plan.
  GET  /api/v3/plans                         list the caller's STORED plans (their
                                            activity_records) newest first as
                                            summaries; optional ?chapter= filter.
  GET  /api/v3/plans/{activity_id}           the caller's full STORED plan for one
                                            activity, in the PreparationPlan shape;
                                            404 if not the caller's.
  GET  /api/v3/chapters/{chapter}/activities the seeded activity options for a
                                            chapter (the app's activity picker).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.models.chapters_v3 import Chapter
from app.models.child_profile import Tag
from app.models.plan import (
    ActivityOption,
    PlanSummary,
    PreparationPlan,
    PreparePlanRequest,
)
from app.services import plans as plans_service

router = APIRouter()

# The today flags are the section 4.4 "today" flags, expressed as the TG- tag
# family. The request accepts only TG- codes here (a permanent profile tag is not a
# day flag); a non-TG- code is a 422.
_TODAY_FLAG_PREFIX = "TG-"


@router.post("/plans", response_model=PreparationPlan)
def create_plan(
    payload: PreparePlanRequest,
    user: AuthedUser = Depends(get_current_user),
) -> PreparationPlan:
    """Prepare an activity: run the engine, store the record, return the plan.

    Validates the chapter is one of the six fixed codes and that every today flag
    is a TG- code (the section 4.4 day flags). Pulls the caller's care recipient
    (support level + permanent tags) inside the service, runs the LCE, persists the
    activity_record (write confirmed), schedules the Pulse, and returns the plan in
    well under 3 seconds (in-memory scoring + one insert). 409 if the caller has no
    care recipient yet (they must finish onboarding first).
    """
    _validate_chapter(payload.chapter)
    today_flags = _today_flag_codes(payload.today_flags)

    try:
        return plans_service.prepare_plan(
            user,
            chapter=payload.chapter,
            activity_code=payload.activity_code,
            today_flags=today_flags,
            activity_date=payload.date,
            context_note=payload.context_note,
        )
    except plans_service.NoCareRecipientError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No care recipient found; complete onboarding first",
        ) from exc


@router.get("/plans", response_model=List[PlanSummary])
def list_plans(
    chapter: Optional[str] = Query(default=None),
    user: AuthedUser = Depends(get_current_user),
) -> List[PlanSummary]:
    """The caller's STORED plans (their activity_records), newest first, as summaries.

    Returns one PlanSummary per stored plan: the identity, the stored tier + total, when
    it was prepared, and the pulse status (whether a pulse exists, and whether one is
    currently due). STORED values only, the engine is not re-run. The optional ?chapter=
    filter narrows to one Life Chapter (an unknown chapter code is a 422). The reads are
    user-scoped (the current-user dependency + RLS), so only the caller's own plans are
    listed.
    """
    if chapter is not None:
        _validate_chapter(chapter)
    return plans_service.list_stored_plans(user, chapter=chapter)


@router.get("/plans/{activity_id}", response_model=PreparationPlan)
def get_plan(
    activity_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> PreparationPlan:
    """The caller's full STORED plan for one activity, in the PreparationPlan shape.

    Reads the stored activity_record back and shapes it into the same PreparationPlan the
    POST returns (scores, total, tier, strategies, scheduled_pulse_at); it never re-runs
    the engine, so dimension_explanations is null on this stored read. 404 if the
    activity is unknown or not the caller's (RLS makes another user's row invisible and
    the api does not confirm it exists).
    """
    try:
        return plans_service.get_stored_plan(user, activity_id)
    except plans_service.PlanNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        ) from exc


@router.get("/chapters/{chapter}/activities", response_model=List[ActivityOption])
def list_activities(
    chapter: str,
    user: AuthedUser = Depends(get_current_user),
) -> List[ActivityOption]:
    """The seeded activity options for a chapter (the app's activity picker).

    Validates the chapter code (404 for an unknown chapter). The options are global
    reference data (the same for every user), but the route still requires auth so
    the picker is only reachable by a signed-in Coordinator.
    """
    _validate_chapter(chapter, not_found=True)
    return plans_service.list_chapter_activities(chapter)


def _validate_chapter(chapter: str, *, not_found: bool = False) -> None:
    """Reject a chapter code that is not one of the six fixed Life Chapters.

    A bad chapter in the POST body is a 422 (a malformed request); a bad chapter in
    the GET path is a 404 (no such resource). The valid set is the Chapter enum.
    """
    valid = {c.value for c in Chapter}
    if chapter not in valid:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND if not_found else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=f"Unknown chapter '{chapter}'",
        )


def _today_flag_codes(today_flags: List[Tag]) -> List[str]:
    """Coerce the request's today flags to TG- code strings, rejecting non-TG- tags.

    The section 4.4 today flags are the TG- family; a permanent profile tag (SN-/
    TR-/CM-/RC-) is not a day flag and is a 422 here. Returns the plain string codes
    the engine reads.
    """
    codes = [t.value for t in today_flags]
    bad = [c for c in codes if not c.startswith(_TODAY_FLAG_PREFIX)]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"today_flags must be TG- codes; got {bad}",
        )
    return codes
