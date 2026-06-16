"""The governed-copy guard for the per-chapter ENGAGEMENT signal.

The engagement signal (the owner's "disengagement" Tier-1 idea, owner-track Task 12: "a
previously-active chapter going quiet"; the researcher + psychiatrist boards' HONEST shape)
is a per-chapter, deterministic, server-side band ("quiet" / "resting") derived from how
long it has been since the last PREPARED activity in that chapter. It is decline-adjacent,
so its copy is GOVERNED: every emitted string must be FACTUAL about the plan record (never
the carer as the subject of a failure), warm, and free of the shame / streak / deficit
register.

This module is the single definition of THIS surface's prohibited words and the guard that
enforces them on every emitted string. It is the analogue of app/engines/checkin/guard.py
and app/engines/alerts/guard.py: assert_clean() runs at emit time so a violating string can
never leave the engine, and a permanent guard test (tests/test_engine_engagement_guard.py)
asserts none of these strings ever appears in ANY emitted engagement copy.

THE TWO PROHIBITED CATEGORIES (the boards' conditions):
  1. CLINICAL words. TIWANI is non-clinical infrastructure (root CLAUDE.md): the signal
     reports a planning record, it does not assess a mental state (the medical-device line,
     Psychiatrist.md). The SAME clinical vocabulary the Erosion Alert guard bars is barred
     here, IMPORTED verbatim so there is ONE clinical-words authority across the product (the
     village / check-in precedent). A future addition to the Product.md section 4.9 list
     propagates here automatically (no silent drift).
  2. SHAME / DEFICIT / STREAK words. The boards were explicit that a quiet-chapter signal
     must NEVER shame the carer or frame a gap as a failure, a deficit, or a broken streak
     (Psychiatrist.md: "no streaks, badges, levels, guilt nudges, deficit framing ... on a
     population that already under-asks"). So this surface bars the blame register
     ("abandoned", "dormant", "neglected", "overdue", "behind", "failing", "slipped"), the
     carer-as-subject-of-failure phrasings ("you haven't", "you let"), and the count / trend
     register on the gap ("streak", "down from", "in a row"). The safe register is a flat,
     factual statement about the PLAN record plus a warm forward invitation ("No plan
     prepared here in over 8 weeks", "Here whenever you're ready"), never a count and never
     a verdict on the carer.

The constraint is the product, not a preference: if a future copy edit needs one of these
concepts it does not ship without the product owner AND the psychiatrist sign-off that gates
this surface (Task 12). Matched case-insensitively as substrings.
"""

from __future__ import annotations

from typing import Iterable

# CATEGORY 1: clinical words. The SAME governed set the Erosion Alert guard owns
# (app/engines/alerts/guard.py), IMPORTED rather than re-declared so there is ONE
# clinical-words authority across the product (root CLAUDE.md). The alert guard matches
# these as case-insensitive substrings; this guard does the same below. Do not soften
# without the product owner + psychiatrist sign-off (Task 12).
from app.engines.alerts.guard import PROHIBITED_WORDS as _CLINICAL_WORDS

# CATEGORY 2: the shame / deficit / streak register the boards rejected for a quiet-chapter
# signal. Barred as case-insensitive substrings, so the word is caught wherever it appears.
# Two groups: the BLAME / VERDICT words that frame a gap as a failure or the carer as having
# let something slip, and the COUNT / TREND words that turn the gap into a streak or a
# deficit. These are the exact governed bans; do not add, remove, or soften an entry without
# the product owner + psychiatrist sign-off (Task 12).
_SHAME_AND_STREAK_WORDS = (
    # blame / verdict on the chapter or the carer
    "abandoned",
    "dormant",
    "neglected",
    "overdue",
    "behind",
    "failing",
    "slipped",
    # the carer as the subject of a failure sentence
    "you haven't",
    "you havent",
    "you let",
    # count / streak / deficit on the gap
    "streak",
    "down from",
    "in a row",
)

# The full governed prohibited set this guard enforces: the shared clinical words first, then
# the shame / deficit / streak words. find_prohibited_words reports any that appear, in this
# order. This is the exact governed list; do not change an entry without the product owner and
# the psychiatrist sign-off (Task 12).
PROHIBITED_WORDS = _CLINICAL_WORDS + _SHAME_AND_STREAK_WORDS

# Exposed so a test can pin the clinical set is still a strict subset (no drift from the
# section 4.9 authority) and the shame / streak set is exactly the governed words.
CLINICAL_WORDS = _CLINICAL_WORDS
SHAME_AND_STREAK_WORDS = _SHAME_AND_STREAK_WORDS


class ProhibitedCopyError(ValueError):
    """Raised when emitted engagement copy contains a prohibited word.

    A programming / governance error, never a runtime user error: it means a copy string
    broke the factual, warm, non-clinical, non-shaming constraint and must be fixed before it
    can ship. Surfaced loudly (an exception) rather than silently scrubbed, the same posture
    as the Erosion Alert and check-in guards.
    """


def find_prohibited_words(text: str) -> list[str]:
    """The prohibited words present in `text` (case-insensitive substring match).

    Returns each prohibited entry that appears, in the PROHIBITED_WORDS order, so a caller (or
    the guard test) can report exactly what was found. Empty list means the text is clean.
    """
    lowered = text.lower()
    return [word for word in PROHIBITED_WORDS if word in lowered]


def assert_clean(*texts: str) -> None:
    """Raise ProhibitedCopyError if any given string contains a prohibited word.

    Called at emit time over every governed engagement string (each band's label, factual
    note, and forward invitation) so a violating string can never leave the engine, and used
    by the guard test over all governed copy. Accepts several strings so one call covers a
    whole rendered signal.
    """
    for text in texts:
        found = find_prohibited_words(text)
        if found:
            raise ProhibitedCopyError(
                "Engagement copy contains prohibited words "
                f"{found!r}: the engagement signal is a FACTUAL, warm statement about the "
                "plan record, never clinical and never a shame / deficit / streak framing "
                "(owner-track Task 12, the psychiatrist's no-deficit-mechanic condition)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
