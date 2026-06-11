"""Life Chapter dashboard data service (v3).

The thin data layer behind GET /api/v3/chapters. It assembles, per chapter for
the current user, the ChapterStatus inputs the dashboard needs (the chapter LCI,
the active alert level, the last-prepared timestamp, and the activity count). No
engine logic and no status-colour mapping live here: this returns raw inputs, the
app maps them to the section 4.3 bands.

User scoping (HardRules/Api/Modules/Auth.md): the function takes the resolved
AuthedUser, so every value it ever reads is scoped to that user. The six chapters
are a FIXED set (always all six, in a stable order), so the list itself is not
user-specific; only the per-chapter values are, and they are filled from the
user's own rows.

State today: activity_record (Task 5), the LCI (Task 6), and Erosion Alerts
(Task 7) do not exist yet, so there is nothing per-user to read and every chapter
comes back "not started" (lci=null, alert_level=null, last_prepared_at=null,
activity_count=0): the correct baseline for a fresh user. This is written to fill
those values in when those tables exist and to TOLERATE an empty result set
(absent rows leave a chapter at the not-started baseline), so wiring Tasks 5 to 7
is an additive change here, not a rewrite.
"""

from __future__ import annotations

from typing import List

from app.auth import AuthedUser
from app.models.chapters_v3 import CHAPTER_DISPLAY_NAMES, Chapter, ChapterStatus


def list_chapter_statuses(user: AuthedUser) -> List[ChapterStatus]:
    """Return the six fixed Life Chapters for the user, each a ChapterStatus.

    Always returns all six chapters in the stable Chapter declaration order
    (School first), so the dashboard grid is deterministic. For a fresh user
    every chapter is at the not-started baseline (lci=null, alert_level=null,
    last_prepared_at=null, activity_count=0).

    The user argument is the scope key: when activity_record / chapter_lci_record
    / alert_record exist (Tasks 5 to 7), this reads the user's rows (RLS-scoped via
    get_anon_client(user.access_token)) and fills lci, alert_level,
    last_prepared_at, and activity_count per chapter, defaulting any chapter with
    no rows to the baseline. Until then there is nothing to read, so it builds the
    baseline list directly.
    """
    # user is unused while there are no per-user chapter rows to read; it is part
    # of the signature so the scoping is in place and Tasks 5 to 7 fill the values
    # without changing the route or the contract.
    _ = user
    return [
        ChapterStatus(chapter=chapter, display_name=CHAPTER_DISPLAY_NAMES[chapter])
        for chapter in Chapter
    ]
