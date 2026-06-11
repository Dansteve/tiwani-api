"""v3 Life Chapter dashboard route.

Thin HTTP only (HardRules/Api/SETUP.md): parse, call the chapters service,
serialize. Behind the current-user dependency (401 if the bearer token is missing
or invalid); the response is user-scoped through the service. This is the api half
of Task 4 (the six-chapter dashboard, Product.md section 4.3).

Registered under /api/v3 in main.py, so the path is /api/v3/chapters, alongside
the other v3 routes (profile_v3) and the prototype /api/chapters (the pre-v3
"chapters + triggers + status" routes, replaced in the rebuild). Named
chapters_v3 to sit beside the prototype app/routes/chapters.py without colliding.

Endpoint:
  GET /api/v3/chapters   the six fixed Life Chapters, each a ChapterStatus, for
                         the current user (all "not started" for a fresh user).

The api returns raw inputs only (per chapter: the LCI if any, the active alert
level if any, the last-prepared timestamp, the activity count); it does NOT
compute the status colour. The app maps those inputs to grey / green / amber / red
per section 4.3.
"""

from typing import List

from fastapi import APIRouter, Depends

from app.auth import AuthedUser, get_current_user
from app.models.chapters_v3 import ChapterStatus
from app.services import chapters as chapters_service

router = APIRouter()


@router.get("/chapters", response_model=List[ChapterStatus])
def list_chapters(user: AuthedUser = Depends(get_current_user)) -> List[ChapterStatus]:
    """Return the six fixed Life Chapters for the caller, each a ChapterStatus.

    Always all six, in a stable order (School first). For a fresh user every
    chapter is "not started" (lci=null, alert_level=null, last_prepared_at=null,
    activity_count=0); the per-chapter values fill in as activities, the LCI, and
    alerts arrive (Tasks 5 to 7). Auth is required (401 without a valid token).
    """
    return chapters_service.list_chapter_statuses(user)
