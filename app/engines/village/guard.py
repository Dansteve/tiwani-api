"""The governed-copy guard for the Village Delegation Hub (Docs/FeatureDecisions.md).

The Village Hub lets a Coordinator's village (family / friends / trusted helpers)
VOLUNTEER for a specific bounded NEED. The user-facing copy (the need framing, the
claim / confirm / done / drop confirmations, the per-recipient consent text) is GOVERNED
(the Village Hub decision, refinement 6): it must be WARM and CAPACITY-FRAMED, and it
must NEVER use clinical words, NEVER use surveillance language, and NEVER expose the
internal RBAC role labels ("viewer" / "owner") as user-facing words.

This module is the single definition of the Hub's prohibited words and the guard that
enforces them on every emitted string. It is the Hub's analogue of
app/engines/alerts/guard.py: assert_clean() runs at emit time so a violating string can
never leave the engine, and a permanent guard test (tests/test_engine_village_guard.py)
asserts none of these strings ever appears in ANY emitted Hub copy.

THE THREE PROHIBITED CATEGORIES (the Village Hub decision):
  1. CLINICAL words. TIWANI is non-clinical infrastructure (root CLAUDE.md): the Hub is a
     practical help-coordination surface, not a care-monitoring one. The same clinical
     vocabulary the Erosion Alert guard bars is barred here.
  2. SURVEILLANCE / monitoring words. The board was explicit (refinement 3): NO
     "monitor / track / surveillance / case / subject" language. A standing record of a
     vulnerable person's routine handed to a wide circle is a grooming / stalking /
     coercive-control surface, and even the WORDS frame the helper as a watcher rather
     than a neighbour lending a hand. The Hub redistributes a task, it does not surveil a
     person.
  3. The internal ROLE LABELS as user-facing words. "viewer" / "owner" are the RLS
     primitive's role names (recipient_membership.role, migration 0015); the board
     requires they are NEVER user-facing labels (the Shared-Child refinement 7, carried
     into the Hub). The Coordinator and the village see warm human words ("you",
     "[name]'s village", "the family"), not the database's role vocabulary.

The constraint is the product, not a preference: if a future copy edit needs one of these
concepts it does not ship without the product owner and the psychiatrist sign-off (Task
12). Matched case-insensitively as substrings.
"""

from __future__ import annotations

import re
from typing import Iterable

# CATEGORY 1: clinical words (the same governed set as the Erosion Alert guard,
# app/engines/alerts/guard.py: kept identical so the non-clinical bar is one bar across
# the product). Do not soften without the product owner + psychiatrist sign-off.
_CLINICAL_WORDS = (
    "symptoms",
    "diagnosis",
    "condition",
    "mental health",
    "depression",
    "anxiety disorder",
    "clinical",
    "treatment",
    "therapy",
)

# CATEGORY 2: surveillance / monitoring words (the Village Hub decision, refinement 3,
# verbatim: no "monitor / track / surveillance / case / subject"). "case" and "subject"
# are matched as standalone words via the WORD_BOUNDED set below (so "staircase" or
# "subject line" do not false-trigger); "monitor", "track", and "surveillance" are barred
# as substrings (there is no benign Hub use of them, and "tracking" / "monitoring" must be
# caught too).
_SURVEILLANCE_SUBSTRINGS = (
    "monitor",
    "surveillance",
    "track",
)

# CATEGORY 3: the internal RBAC role labels, never user-facing (refinement, Shared-Child 7
# carried into the Hub). Word-bounded so the database column name in a comment is not the
# concern here (this guards EMITTED user-facing copy): "viewer" / "owner" as a word the
# Coordinator or a helper would read.
# CATEGORY 2 + 3 word-bounded entries: barred only as standalone words (a regex word
# boundary), so a legitimate longer word is not a false positive.
_WORD_BOUNDED = (
    "case",
    "subject",
    "viewer",
    "owner",
)

# The full governed prohibited set the Hub guard enforces. SUBSTRING entries first
# (clinical + surveillance substrings), then the word-bounded entries. find_prohibited_words
# reports any that appear. This is the exact governed list; do not add, remove, or soften
# an entry without the product owner and the psychiatrist sign-off (Task 12).
PROHIBITED_SUBSTRINGS = _CLINICAL_WORDS + _SURVEILLANCE_SUBSTRINGS
PROHIBITED_WORD_BOUNDED = _WORD_BOUNDED

# The combined view (for the guard test to pin the whole governed set in one place).
PROHIBITED_WORDS = PROHIBITED_SUBSTRINGS + PROHIBITED_WORD_BOUNDED


class ProhibitedCopyError(ValueError):
    """Raised when emitted Village Hub copy contains a prohibited word.

    A programming / governance error, never a runtime user error: it means a copy string
    broke the warm, non-clinical, non-surveillance constraint (or leaked an internal role
    label) and must be fixed before it can ship. Surfaced loudly (an exception) rather
    than silently scrubbed, the same posture as the Erosion Alert guard.
    """


def _word_present(word: str, lowered: str) -> bool:
    """True if `word` appears in `lowered` as a standalone word (regex word boundary).

    Used for the word-bounded entries ("case" / "subject" / "viewer" / "owner") so a
    benign longer word ("staircase", "downtown", "lowercase") is not a false positive,
    while the standalone surveillance / role word is caught.
    """
    return re.search(rf"\b{re.escape(word)}\b", lowered) is not None


def find_prohibited_words(text: str) -> list[str]:
    """The prohibited words present in `text` (case-insensitive).

    Substring entries (clinical + monitor / surveillance / track) match anywhere; the
    word-bounded entries (case / subject / viewer / owner) match only as standalone words.
    Returns each prohibited entry that appears, in the PROHIBITED_WORDS order, so a caller
    (or the guard test) can report exactly what was found. Empty list means the text is
    clean.
    """
    lowered = text.lower()
    found: list[str] = []
    for word in PROHIBITED_SUBSTRINGS:
        if word in lowered:
            found.append(word)
    for word in PROHIBITED_WORD_BOUNDED:
        if _word_present(word, lowered):
            found.append(word)
    return found


def assert_clean(*texts: str) -> None:
    """Raise ProhibitedCopyError if any given string contains a prohibited word.

    Called at emit time over every governed Hub string (the need framing, each
    confirmation, the consent text) so a violating string can never leave the engine, and
    used by the guard test over all governed copy. Accepts several strings so one call
    covers a whole rendered surface.
    """
    for text in texts:
        found = find_prohibited_words(text)
        if found:
            raise ProhibitedCopyError(
                "Village Hub copy contains prohibited words "
                f"{found!r}: Hub copy is warm and capacity-framed, never clinical, never "
                "surveillance language, and never an internal role label "
                "(Docs/FeatureDecisions.md, the Village Hub decision)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
