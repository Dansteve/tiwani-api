"""The governed-copy guard for the carer check-in moment ("A moment for you").

The check-in moment (ProductReview.md item 9, the sanctioned "today is hard" entry;
the psychiatrist board's SAFE shape) is an OPTIONAL, occasional, SIGNPOST-ONLY
acknowledgement of the carer that points to real community/statutory support and a
crisis-capable carer route. It NEVER measures or scores the carer (no mood scale, no
assessment), it stores NOTHING, and its copy is GOVERNED: every emitted string must be
warm, honest, non-clinical, and free of the hollow-affirmation register.

This module is the single definition of THIS surface's prohibited words and the guard
that enforces them on every emitted string. It is the moment's analogue of
app/engines/alerts/guard.py: assert_clean() runs at emit time so a violating string can
never leave the engine, and a permanent guard test (tests/test_engine_checkin_guard.py)
asserts none of these strings ever appears in ANY emitted moment copy.

THE TWO PROHIBITED CATEGORIES (the psychiatrist's conditions, esp. condition 4):
  1. CLINICAL words. TIWANI is non-clinical infrastructure (root CLAUDE.md): the moment
     signposts support, it does not assess a mental state (the medical-device line,
     Psychiatrist.md). The SAME clinical vocabulary the Erosion Alert guard bars is
     barred here, IMPORTED verbatim so there is ONE clinical-words authority across the
     product (the village precedent). A future addition to the Product.md section 4.9
     list propagates here automatically (no silent drift).
  2. HOLLOW-AFFIRMATION words. The board was explicit: the owner's "return motivation"
     shape was rejected as hollow and as surfacing un-holdable distress. So this surface
     additionally bars the cheer-up / toxic-positivity register ("you've got this",
     "stay strong", "you're amazing", "be positive", "don't worry"): to a carer in a
     hard moment, a hollow affirmation lands as dismissal, not support. The safe register
     is calm, honest acknowledgement plus a real route to help ("you do not have to
     manage this alone"), the section 4.9 L3 tone, never a pep talk.

The constraint is the product, not a preference: if a future copy edit needs one of these
concepts it does not ship without the product owner AND the psychiatrist + DPO sign-off
that gates this surface (Task 12). Matched case-insensitively as substrings.
"""

from __future__ import annotations

from typing import Iterable

# CATEGORY 1: clinical words. The SAME governed set the Erosion Alert guard owns
# (app/engines/alerts/guard.py), IMPORTED rather than re-declared so there is ONE
# clinical-words authority across the product (root CLAUDE.md). The alert guard matches
# these as case-insensitive substrings; this guard does the same below. Do not soften
# without the product owner + psychiatrist sign-off (Task 12).
from app.engines.alerts.guard import PROHIBITED_WORDS as _CLINICAL_WORDS

# CATEGORY 2: the hollow-affirmation / toxic-positivity register (the psychiatrist's
# rejection of the "return motivation" shape). Barred as case-insensitive substrings, so
# the phrase is caught wherever it appears. These are the exact governed phrases plus the
# near-variants a copy edit might reach for ("you can do this", "you got this", "you are
# strong", "everything will be okay"); a hollow affirmation to a carer in a hard moment
# reads as dismissal. Do not add, remove, or soften without the product owner +
# psychiatrist sign-off (Task 12).
_HOLLOW_AFFIRMATION_WORDS = (
    "you've got this",
    "youve got this",
    "you got this",
    "you can do this",
    "stay strong",
    "be strong",
    "you are strong",
    "you're strong",
    "youre strong",
    "you're amazing",
    "youre amazing",
    "you are amazing",
    "be positive",
    "stay positive",
    "think positive",
    "don't worry",
    "dont worry",
    "everything will be okay",
    "everything will be ok",
    "everything happens for a reason",
    "good vibes",
    "chin up",
)

# The full governed prohibited set this guard enforces: the shared clinical words first,
# then the hollow-affirmation phrases. find_prohibited_words reports any that appear, in
# this order. This is the exact governed list; do not change an entry without the product
# owner and the psychiatrist + DPO sign-off (Task 12).
PROHIBITED_WORDS = _CLINICAL_WORDS + _HOLLOW_AFFIRMATION_WORDS

# Exposed so a test can pin the clinical set is still a strict subset (no drift from the
# section 4.9 authority) and the hollow-affirmation set is exactly the governed phrases.
CLINICAL_WORDS = _CLINICAL_WORDS
HOLLOW_AFFIRMATION_WORDS = _HOLLOW_AFFIRMATION_WORDS


class ProhibitedCopyError(ValueError):
    """Raised when emitted check-in-moment copy contains a prohibited word.

    A programming / governance error, never a runtime user error: it means a copy string
    broke the warm, honest, non-clinical, non-affirmation constraint and must be fixed
    before it can ship. Surfaced loudly (an exception) rather than silently scrubbed, the
    same posture as the Erosion Alert guard.
    """


def find_prohibited_words(text: str) -> list[str]:
    """The prohibited words present in `text` (case-insensitive substring match).

    Returns each prohibited entry that appears, in the PROHIBITED_WORDS order, so a caller
    (or the guard test) can report exactly what was found. Empty list means the text is
    clean.
    """
    lowered = text.lower()
    return [word for word in PROHIBITED_WORDS if word in lowered]


def assert_clean(*texts: str) -> None:
    """Raise ProhibitedCopyError if any given string contains a prohibited word.

    Called at emit time over every governed moment string (the intro, each tap label,
    each acknowledgement, every signpost label) so a violating string can never leave the
    engine, and used by the guard test over all governed copy. Accepts several strings so
    one call covers a whole rendered response.
    """
    for text in texts:
        found = find_prohibited_words(text)
        if found:
            raise ProhibitedCopyError(
                "Check-in moment copy contains prohibited words "
                f"{found!r}: the moment is warm, honest signposting, never clinical and "
                "never a hollow affirmation (ProductReview.md item 9, the psychiatrist's "
                "SAFE shape)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
