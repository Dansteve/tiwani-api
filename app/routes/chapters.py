"""v1 Life Chapter dashboard route.

Thin HTTP only (HardRules/Api/SETUP.md): parse, call the chapters service,
serialize. Behind the current-user dependency (401 if the bearer token is missing
or invalid); the response is user-scoped through the service. This is the api half
of Task 4 (the six-chapter dashboard, Product.md section 4.3).

Registered under /api/v1 in main.py, so the path is /api/v1/chapters, alongside
the other v1 routes (profile) and the prototype /api/chapters (the pre-v3
"chapters + triggers + status" routes, replaced in the rebuild). Named
chapters to sit beside the prototype app/routes/chapters.py without colliding.

Endpoints:
  GET /api/v1/chapters                        the six fixed Life Chapters, each a
                                              ChapterStatus, for the current user (all
                                              "not started" for a fresh user).
  GET /api/v1/chapters/{chapter}/last-outcome the family's OWN most recent prior outcome
                                              in the chapter (ProductReview.md item 5,
                                              "What helped last time"); null on a first-time
                                              chapter. A READ of stored facts, no scoring.

The api returns raw inputs only (per chapter: the LCI if any, the active alert
level if any, the last-prepared timestamp, the activity count); it does NOT
compute the status colour. The app maps those inputs to grey / green / amber / red
per section 4.3.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.models.chapters import Chapter, ChapterStatus
from app.models.last_outcome import LastOutcome
from app.services import chapters as chapters_service
from app.services import last_outcome as last_outcome_service
from app.services import profile as profile_service

router = APIRouter()


@router.get("/chapters", response_model=List[ChapterStatus])
def list_chapters(
    user: AuthedUser = Depends(get_current_user),
    child_id: Optional[str] = Query(
        default=None,
        description=(
            "Which care recipient's dashboard to return. Defaults to the caller's sole "
            "recipient (back-compat while only one is supported); the future app switcher "
            "passes the active child_id. 404 if the id is not one the caller owns."
        ),
    ),
) -> List[ChapterStatus]:
    """Return the six fixed Life Chapters for ONE care recipient, each a ChapterStatus.

    Always all six, in a stable order (School first). The dashboard is per recipient:
    child_id selects which one (defaulting to the caller's sole recipient); every
    per-chapter value (activity count, LCI, alert level) is for that recipient only and
    never mixes two. For a fresh recipient every chapter is "not started" (lci=null,
    alert_level=null, last_prepared_at=null, activity_count=0). Auth is required (401
    without a valid token); a child_id the caller does not own is a 404.
    """
    try:
        return chapters_service.list_chapter_statuses(user, child_id)
    except profile_service.ChildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        ) from exc


@router.get("/chapters/{chapter}/last-outcome", response_model=Optional[LastOutcome])
def get_last_outcome(
    chapter: str,
    user: AuthedUser = Depends(get_current_user),
    child_id: Optional[str] = Query(
        default=None,
        description=(
            "Which care recipient's recall to return. Defaults to the caller's sole "
            "recipient; the app switcher passes the active child_id. 404 if not owned."
        ),
    ),
) -> Optional[LastOutcome]:
    """The family's OWN most recent prior outcome in a chapter ("What helped last time").

    A READ of stored facts (ProductReview.md item 5): the most recent prior COMPLETED (non
    skipped) pulse in the chapter for ONE recipient, with its stored outcome + recommended
    tier + named challenge dimension, plus the title of a §4.10 PROMOTED strategy that has
    worked for the recipient + chapter, and the grounded pivot_helped flag. It does NO
    scoring (no LCE run, no tier re-derivation, no index): every field is a value already
    stored. Returns null (a 200 with a null body) for a FIRST-TIME chapter (no prior
    completed pulse), so the app suppresses the calm "Last time here" note.

    Auth is required (401 without a valid token). The chapter must be one of the six fixed
    codes (an unknown chapter is a 404, like the activity picker). child_id selects the
    recipient (defaulting to the caller's sole one); a child_id the caller does not own is a
    404 (it is invisible under RLS, so the resolver reads it as not-found).
    """
    if chapter not in {c.value for c in Chapter}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown chapter '{chapter}'",
        )
    try:
        return last_outcome_service.get_last_outcome(
            user, chapter=chapter, child_id=child_id
        )
    except profile_service.ChildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        ) from exc
