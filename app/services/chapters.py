"""Life Chapter dashboard data service (v3).

The thin data layer behind GET /api/v1/chapters. It assembles, per chapter for
the current user, the ChapterStatus inputs the dashboard needs (the chapter LCI,
the active alert level, the last-prepared timestamp, and the activity count). No
engine logic and no status-colour mapping live here: this returns raw inputs, the
app maps them to the section 4.3 bands.

User + recipient scoping (Auth.md; Docs/FeatureDecisions.md, the multi care recipient
design note): the function takes the resolved AuthedUser and reads the user's
activity_record rows through get_anon_client(user.access_token), so Row Level Security
scopes every value to that user. On top of RLS, the dashboard is PER RECIPIENT: it
resolves which care recipient once (profile.resolve_child_id, an explicit child_id
verified owned, else the caller's sole child) and threads that one child_id into the
activity aggregates, the LCI scores, and the alert levels, so a chapter card never mixes
two recipients (the isolation rule). A caller with no recipient yet resolves to None and
every chapter is the not-started baseline. The six chapters are a FIXED set (always all
six, in a stable order), so the list itself is not user-specific; only the per-chapter
values are.

State (2026-06-11, Task 7 wired): activity_record (Task 5), pulse_record + lci_snapshot
(Task 6), and alert_record (Task 7) all EXIST, so activity_count and last_prepared_at
come from the user's prepared activities per chapter, lci is the chapter's Life
Continuity Index (section 4.8) once a chapter has at least one pulse (null before
that), and alert_level is the chapter's ACTIVE (non-dismissed) Erosion Alert level
(section 4.9, from alerts_service) or null when none is raised. A chapter with no
activities is the not-started baseline (count 0, no timestamp, no LCI, no alert).

The LCI value comes from the SAME fold the LCI dashboard uses (lci_service), so the
chapter card and the LCI dashboard always agree; this service never does index math.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.auth import AuthedUser
from app.db import get_anon_client
from app.models.chapters import CHAPTER_DISPLAY_NAMES, Chapter, ChapterStatus
from app.services import alerts as alerts_service
from app.services import lci as lci_service
from app.services.profile import _rows, resolve_child_id

ACTIVITY_RECORD_TABLE = "activity_record"


def list_chapter_statuses(
    user: AuthedUser, child_id: Optional[str] = None
) -> List[ChapterStatus]:
    """Return the six fixed Life Chapters for ONE care recipient, each a ChapterStatus.

    Resolves which recipient once (profile.resolve_child_id, an explicit child_id verified
    owned, else the caller's sole child) and threads that one id into every per-chapter
    value, so the dashboard is for exactly one recipient and never mixes two (the isolation
    rule). Always returns all six chapters in the stable Chapter declaration order (School
    first), so the dashboard grid is deterministic. activity_count and last_prepared_at are
    filled from THIS recipient's activity_record rows per chapter (RLS + child_id scoped);
    lci is the chapter's section 4.8 index for this recipient once it has a pulse (null
    before), from the shared lci_service fold; alert_level is this recipient's active
    section 4.9 Erosion Alert level (null when none), from the shared alerts_service. A
    chapter with no prepared activities (or a caller with no recipient yet) is the
    not-started baseline (count 0, no timestamp, no LCI, no alert).
    """
    resolved_child_id = resolve_child_id(user, child_id)
    counts, last_prepared = _activity_aggregates_by_chapter(user, resolved_child_id)
    lci_by_chapter = lci_service.chapter_scores_by_code(user, resolved_child_id)
    alert_levels = alerts_service.active_levels_by_chapter(user, resolved_child_id)
    return [
        ChapterStatus(
            chapter=chapter,
            display_name=CHAPTER_DISPLAY_NAMES[chapter],
            lci=lci_by_chapter.get(chapter.value),
            alert_level=alert_levels.get(chapter.value),
            activity_count=counts.get(chapter.value, 0),
            last_prepared_at=last_prepared.get(chapter.value),
        )
        for chapter in Chapter
    ]


def _activity_aggregates_by_chapter(
    user: AuthedUser,
    child_id: Optional[str],
) -> Tuple[Dict[str, int], Dict[str, Optional[str]]]:
    """Per chapter: how many activities THIS recipient has, and the most recent time.

    Reads the recipient's activity_record rows (chapter + created_at) under RLS, filtered
    by user_id AND child_id (activity_record has carried child_id since migration 0003),
    and aggregates in Python (the row count is small per user, and grouping here keeps the
    query a single scoped select rather than per-chapter round trips). child_id None (no
    recipient yet) reads nothing (the query is skipped), so every chapter is not-started.
    Returns (counts_by_chapter_code, last_prepared_at_by_chapter_code); last_prepared_at is
    the max created_at as the ISO string the row carries (the app formats it).
    """
    if child_id is None:
        return {}, {}
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("chapter, created_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .execute()
    )

    counts: Dict[str, int] = defaultdict(int)
    last_prepared: Dict[str, Optional[str]] = {}
    for row in rows:
        chapter = row.get("chapter")
        if chapter is None:
            continue
        counts[chapter] += 1
        created_at = _as_iso(row.get("created_at"))
        if created_at is not None:
            current = last_prepared.get(chapter)
            # created_at is an ISO-8601 string; lexical comparison matches
            # chronological order for a fixed-offset/UTC timestamptz, so the max
            # string is the most recent prepared time.
            if current is None or created_at > current:
                last_prepared[chapter] = created_at
    return counts, last_prepared


def _as_iso(value: Any) -> Optional[str]:
    """Normalise a created_at value to an ISO-8601 string (or None)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)
