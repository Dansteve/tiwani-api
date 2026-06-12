"""v1 Erosion Alert routes (the governed early-warning surface).

Thin HTTP only (HardRules/Api/SETUP.md): call the alerts service (which reads the
stored alert_record rows and renders the GOVERNED copy), serialize. Both routes
require the current-user dependency (401 without a valid bearer token); the reads and
the dismissal are user-scoped through the service with Supabase RLS as the backstop.

Registered under /api/v1 in main.py. Alerts are evaluated server-side after every
pulse (section 4.9, AUTHORITATIVE); these routes only expose the ACTIVE alerts and
the dismissal. The copy the app renders is the api's verbatim governed text; the app
never authors or paraphrases it.

GOVERNED COPY + LAUNCH GATE: the alert copy these routes surface does not ship to beta
without psychiatrist sign-off (Task 12 / Product.md section 8 Q6).

Endpoints:
  GET  /api/v1/alerts                    the caller's active (non-dismissed) alerts,
                                         each {chapter, level, copy, action_label,
                                         signposts}.
  POST /api/v1/alerts/{chapter}/dismiss  dismiss a chapter's active alert; it returns
                                         only if conditions worsen past the next
                                         threshold. 404 if no active alert.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.models.alert import AlertView, DismissResult
from app.models.chapters import Chapter
from app.services import alerts as alerts_service
from app.services import profile as profile_service

router = APIRouter()

_CHILD_ID_QUERY = Query(
    default=None,
    description=(
        "Which care recipient's alerts to act on. Defaults to the caller's sole recipient "
        "(back-compat while only one is supported); the future app switcher passes the "
        "active child_id. 404 if the id is not one the caller owns."
    ),
)


@router.get("/alerts", response_model=List[AlertView])
def list_alerts(
    user: AuthedUser = Depends(get_current_user),
    child_id: Optional[str] = _CHILD_ID_QUERY,
) -> List[AlertView]:
    """ONE care recipient's active Erosion Alerts with their governed copy (section 4.9).

    One AlertView per chapter that has an active (non-dismissed) alert FOR THIS recipient,
    in the stable chapter order. Each carries the verbatim section 4.9 prompt (with the
    chapter name substituted), the action label, and the chapter's community/statutory
    signposts. A chapter with no active alert is simply absent. The list is one recipient's
    alerts, never two pooled. child_id selects the recipient (default the sole one); a
    child_id the caller does not own is a 404.
    """
    try:
        return alerts_service.list_active_alerts(user, child_id)
    except profile_service.ChildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        ) from exc


@router.post("/alerts/{chapter}/dismiss", response_model=DismissResult)
def dismiss_alert(
    chapter: Chapter,
    user: AuthedUser = Depends(get_current_user),
    child_id: Optional[str] = _CHILD_ID_QUERY,
) -> DismissResult:
    """Dismiss ONE recipient's chapter alert (section 4.9): it returns only on worsening.

    Marks THAT recipient's active alert for the chapter dismissed and records the level it
    was dismissed at, so the next post-pulse evaluation resurfaces it only if it computes a
    strictly higher level. Dismissing one recipient's alert never touches another
    recipient's alert for the same chapter. 404 if this recipient has no active alert to
    dismiss (or the child_id is not the caller's). `chapter` is the stable chapter code (an
    unknown code is a 422 from the path validation). child_id selects the recipient (default
    the sole one).
    """
    try:
        return alerts_service.dismiss_alert(user, chapter.value, child_id)
    except profile_service.ChildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        ) from exc
    except alerts_service.AlertNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active alert for this chapter",
        ) from exc
