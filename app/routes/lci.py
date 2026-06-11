"""v3 Life Continuity Index routes (the resilience dashboard read endpoints).

Thin HTTP only (HardRules/Api/SETUP.md): call the LCI service (which reads the
stored pulses + snapshots and computes the index via the pure engine), serialize.
Both routes require the current-user dependency (401 without a valid bearer token);
the reads are user-scoped through the service with Supabase RLS as the backstop.

Registered under /api/v3 in main.py. The index is computed server-side (section 4.8,
AUTHORITATIVE); the app renders these values and recomputes no average or trajectory.

Endpoints:
  GET /api/v3/lci/overall   the overall LCI {score|null, trajectory, label,
                            chapters_included, timestamp}.
  GET /api/v3/lci/chapters  the per-chapter LCI list, one per Life Chapter
                            {chapter, score|null, trajectory, pulse_count, label,
                            timestamp}.
"""

from typing import List

from fastapi import APIRouter, Depends

from app.auth import AuthedUser, get_current_user
from app.models.lci import ChapterLci, OverallLci
from app.services import lci as lci_service

router = APIRouter()


@router.get("/lci/overall", response_model=OverallLci)
def get_overall_lci(
    user: AuthedUser = Depends(get_current_user),
) -> OverallLci:
    """The caller's overall Life Continuity Index (section 4.8).

    The equal-weighted mean of the chapter scores that have at least one pulse
    (no-data chapters excluded), its weekly trajectory, the chapters that contributed,
    and the sparse label. score is null until any chapter has a pulse.
    """
    return lci_service.overall_lci(user)


@router.get("/lci/chapters", response_model=List[ChapterLci])
def get_chapter_lci(
    user: AuthedUser = Depends(get_current_user),
) -> List[ChapterLci]:
    """The caller's per-chapter Life Continuity Index, one per Life Chapter (section 4.8).

    Each carries the chapter's current score (null with no pulse, rendered "--"), its
    weekly trajectory, its pulse count, and the sparse "building your picture" label
    for a chapter with fewer than 3 pulses.
    """
    return lci_service.chapter_lci_list(user)
