"""Life Chapter dashboard data service (v3).

The thin data layer behind GET /api/v3/chapters. It assembles, per chapter for
the current user, the ChapterStatus inputs the dashboard needs (the chapter LCI,
the active alert level, the last-prepared timestamp, and the activity count). No
engine logic and no status-colour mapping live here: this returns raw inputs, the
app maps them to the section 4.3 bands.

User scoping (HardRules/Api/Modules/Auth.md): the function takes the resolved
AuthedUser and reads the user's activity_record rows through
get_anon_client(user.access_token), so Row Level Security scopes every value to
that user. The six chapters are a FIXED set (always all six, in a stable order),
so the list itself is not user-specific; only the per-chapter values are.

State (2026-06-11, Task 5 wired): activity_record now EXISTS, so activity_count
and last_prepared_at are filled from the user's own prepared activities per
chapter. The LCI (Task 6) and Erosion Alerts (Task 7) tables do not exist yet, so
lci and alert_level stay null; a chapter with no activities stays at the
not-started baseline (count 0, no timestamp). Wiring Tasks 6/7 is an additive
change here (fill lci/alert_level), not a rewrite.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.auth import AuthedUser
from app.db import get_anon_client
from app.models.chapters_v3 import CHAPTER_DISPLAY_NAMES, Chapter, ChapterStatus
from app.services.profile import _rows

ACTIVITY_RECORD_TABLE = "activity_record"


def list_chapter_statuses(user: AuthedUser) -> List[ChapterStatus]:
    """Return the six fixed Life Chapters for the user, each a ChapterStatus.

    Always returns all six chapters in the stable Chapter declaration order
    (School first), so the dashboard grid is deterministic. activity_count and
    last_prepared_at are filled from the user's activity_record rows per chapter
    (RLS-scoped); lci and alert_level are null until Tasks 6/7 land. A chapter with
    no prepared activities is the not-started baseline (count 0, no timestamp).
    """
    counts, last_prepared = _activity_aggregates_by_chapter(user)
    return [
        ChapterStatus(
            chapter=chapter,
            display_name=CHAPTER_DISPLAY_NAMES[chapter],
            activity_count=counts.get(chapter.value, 0),
            last_prepared_at=last_prepared.get(chapter.value),
        )
        for chapter in Chapter
    ]


def _activity_aggregates_by_chapter(
    user: AuthedUser,
) -> Tuple[Dict[str, int], Dict[str, Optional[str]]]:
    """Per chapter: how many activities the user prepared, and the most recent time.

    Reads the user's activity_record rows (chapter + created_at) under RLS and
    aggregates in Python (the row count is small per user, and grouping here keeps
    the query a single scoped select rather than per-chapter round trips). Returns
    (counts_by_chapter_code, last_prepared_at_by_chapter_code); last_prepared_at is
    the max created_at as the ISO string the row carries (the app formats it).
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("chapter, created_at")
        .eq("user_id", user.id)
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
