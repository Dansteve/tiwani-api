"""The governed-copy guard for the display-only calendar context layer.

The context layer (FeatureDecisions.md 2026-06-19, the Real-World Context Layer Part B)
overlays public calendar dates on the check-in history. It is decline-adjacent, so its
copy is GOVERNED: every emitted string must be a WORLD-FACT (a date), never a verdict on
the check-in signal and never a causal claim. This module is the single definition of
THIS surface's prohibited words + the guard that enforces them at emit time, the analogue
of app/engines/alerts/guard.py and app/engines/engagement/guard.py.

THE TWO PROHIBITED CATEGORIES (the panel's conditions):
  1. CLINICAL words. TIWANI is non-clinical: a calendar date is not a clinical statement.
     The SAME clinical vocabulary the Erosion Alert guard bars is barred here, IMPORTED
     verbatim so there is ONE clinical-words authority across the product (no silent
     drift): a future addition to the section 4.9 list propagates here automatically.
  2. EDITORIALISING / CAUSAL words. The panel was explicit: the context may state a
     world-fact, it may NOT interpret the signal ("seasonal", "normal", "nothing to
     worry about", "as expected", "reassur...") and it may NOT claim a cause ("because",
     "due to", "caused by", "explained by", "explains", "thanks to") or speculate
     ("probably", "likely"). A causal annotation that says a dip happened BECAUSE of the
     holidays is the masking failure the panel rejected; the carer interprets, the
     system reports. Matched case-insensitively as substrings.

The constraint is the product, not a preference: a future copy edit needing one of these
does not ship without the product owner AND the psychiatrist sign-off that gates this
surface (Task 12).
"""

from __future__ import annotations

from typing import Iterable

# CATEGORY 1: clinical words. The SAME governed set the Erosion Alert guard owns
# (app/engines/alerts/guard.py), IMPORTED rather than re-declared so there is ONE
# clinical-words authority across the product. Do not soften without the product owner +
# the psychiatrist sign-off (Task 12).
from app.engines.alerts.guard import PROHIBITED_WORDS as _CLINICAL_WORDS

# CATEGORY 2: the editorialising / causal register the panel rejected for a decline-
# adjacent annotation. Barred as case-insensitive substrings. Two groups: words that
# pass a VERDICT on the check-in signal, and words that claim or speculate a CAUSE. These
# are the exact governed bans; do not add, remove, or soften an entry without the product
# owner + the psychiatrist sign-off (Task 12).
_EDITORIALISING_WORDS = (
    # a verdict on the signal / the dip (never characterise the reading)
    "seasonal",
    "normal",
    "nothing to worry",
    "no need to worry",
    "don't worry",
    "dont worry",
    "as expected",
    "to be expected",
    "reassur",
    # a causal claim (the data cannot attribute a cause for one family's check-ins)
    "because",
    "due to",
    "caused by",
    "explained by",
    "explains",
    "thanks to",
    # speculation
    "probably",
    "likely",
)

# The full governed prohibited set this guard enforces: the shared clinical words first,
# then the editorialising / causal words. find_prohibited_words reports any that appear,
# in this order. This is the exact governed list; do not change an entry without the
# product owner and the psychiatrist sign-off (Task 12).
PROHIBITED_WORDS = _CLINICAL_WORDS + _EDITORIALISING_WORDS

# Exposed so a test can pin the clinical set is still the section 4.9 authority (no drift)
# and the editorialising set is exactly the governed words.
CLINICAL_WORDS = _CLINICAL_WORDS
EDITORIALISING_WORDS = _EDITORIALISING_WORDS


class ProhibitedCopyError(ValueError):
    """Raised when emitted calendar-context copy contains a prohibited word.

    A programming / governance error, never a runtime user error: it means a copy string
    broke the world-fact, non-clinical, non-editorialising constraint and must be fixed
    before it can ship. Surfaced loudly (an exception) rather than silently scrubbed, the
    same posture as the Erosion Alert and engagement guards.
    """


def find_prohibited_words(text: str) -> list[str]:
    """The prohibited words present in `text` (case-insensitive substring match).

    Returns each prohibited entry that appears, in the PROHIBITED_WORDS order, so a caller
    (or the guard test) can report exactly what was found. Empty list means clean.
    """
    lowered = text.lower()
    return [word for word in PROHIBITED_WORDS if word in lowered]


def assert_clean(*texts: str) -> None:
    """Raise ProhibitedCopyError if any given string contains a prohibited word.

    Called at emit time over every governed calendar string (the intro, the hedge, and
    each window note) so a violating string can never leave the engine, and used by the
    guard test over all governed copy.
    """
    for text in texts:
        found = find_prohibited_words(text)
        if found:
            raise ProhibitedCopyError(
                "Calendar context copy contains prohibited words "
                f"{found!r}: the context layer states a WORLD-FACT (a public date), "
                "never a clinical statement, a verdict on the check-in signal, or a "
                "causal claim (FeatureDecisions.md 2026-06-19, the psychiatrist + "
                "researcher conditions)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
