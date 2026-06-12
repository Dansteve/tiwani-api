"""v1 Life Continuity Index routes (the resilience dashboard read endpoints).

Thin HTTP only (HardRules/Api/SETUP.md): call the LCI service (which reads the
stored pulses + snapshots and computes the index via the pure engine), serialize.
Both routes require the current-user dependency (401 without a valid bearer token);
the reads are user-scoped through the service with Supabase RLS as the backstop.

Registered under /api/v1 in main.py. The index is computed server-side (section 4.8,
AUTHORITATIVE); the app renders these values and recomputes no average or trajectory.

Endpoints:
  GET /api/v1/lci/overall   the overall LCI {score|null, trajectory, label,
                            chapters_included, timestamp}.
  GET /api/v1/lci/chapters  the per-chapter LCI list, one per Life Chapter
                            {chapter, score|null, trajectory, pulse_count, label,
                            timestamp}.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.models.lci import ChapterLci, OverallLci
from app.services import lci as lci_service
from app.services import profile as profile_service

router = APIRouter()

_CHILD_ID_QUERY = Query(
    default=None,
    description=(
        "Which care recipient's index to return. Defaults to the caller's sole recipient "
        "(back-compat while only one is supported); the future app switcher passes the "
        "active child_id. 404 if the id is not one the caller owns."
    ),
)


@router.get("/lci/overall", response_model=OverallLci)
def get_overall_lci(
    user: AuthedUser = Depends(get_current_user),
    child_id: Optional[str] = _CHILD_ID_QUERY,
) -> OverallLci:
    """ONE care recipient's overall Life Continuity Index (section 4.8).

    The equal-weighted mean of THAT recipient's chapter scores that have at least one pulse
    (no-data chapters excluded), its weekly trajectory, the chapters that contributed, and
    the sparse label. score is null until any chapter has a pulse. The overall is a single
    recipient's resilience, never a household-aggregate across recipients. child_id selects
    the recipient (default the sole one); a child_id the caller does not own is a 404.
    """
    try:
        return lci_service.overall_lci(user, child_id=child_id)
    except profile_service.ChildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        ) from exc


@router.get("/lci/chapters", response_model=List[ChapterLci])
def get_chapter_lci(
    user: AuthedUser = Depends(get_current_user),
    child_id: Optional[str] = _CHILD_ID_QUERY,
) -> List[ChapterLci]:
    """ONE care recipient's per-chapter Life Continuity Index, one per Life Chapter (section 4.8).

    Each carries the chapter's current score (null with no pulse, rendered "--"), its
    weekly trajectory, its pulse count, and the sparse "building your picture" label for a
    chapter with fewer than 3 pulses. Every value is for the selected recipient only.
    child_id selects the recipient (default the sole one); a child_id the caller does not
    own is a 404.
    """
    try:
        return lci_service.chapter_lci_list(user, child_id=child_id)
    except profile_service.ChildNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        ) from exc
