"""The non-clinical guard for Erosion Alert content (Product.md section 4.9).

TIWANI stores participation-planning data only and is non-clinical infrastructure
(root CLAUDE.md). Alert copy may only signpost COMMUNITY and STATUTORY support and
must never use clinical vocabulary. This module is the single definition of the
prohibited words and the guard that enforces the rule on every emitted string.

The constraint is the product, not a preference: if a future copy edit needs one of
these concepts it does not ship. A permanent guard test
(tests/test_engine_alerts_guard.py) asserts none of these strings ever appears in
ANY emitted alert content (every chapter, every level: the prompt, the action label,
and every signpost label), and assert_clean() is also called at render time so a
violating string can never leave the engine.
"""

from __future__ import annotations

from typing import Iterable

# The words PROHIBITED in all alert copy and any alert-attached text (Product.md
# section 4.9, HardRules/Api/Modules/Alerts.md). Matched case-insensitively as
# substrings, so "Clinical" and "CLINICAL" are caught as well as "clinical". This is
# the exact governed list; do not add, remove, or soften an entry without the
# product owner and the psychiatrist sign-off (Task 12).
PROHIBITED_WORDS = (
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


class ProhibitedWordError(ValueError):
    """Raised when emitted alert content contains a prohibited clinical word.

    A programming/governance error, never a runtime user error: it means a copy or
    signpost string broke the non-clinical constraint and must be fixed before it can
    ship. Surfaced loudly (an exception) rather than silently scrubbed.
    """


def find_prohibited_words(text: str) -> list[str]:
    """The prohibited words present in `text` (case-insensitive substring match).

    Returns each prohibited entry that appears, in the PROHIBITED_WORDS order, so a
    caller (or the guard test) can report exactly what was found. Empty list means
    the text is clean.
    """
    lowered = text.lower()
    return [word for word in PROHIBITED_WORDS if word in lowered]


def assert_clean(*texts: str) -> None:
    """Raise ProhibitedWordError if any of the given strings contains a prohibited word.

    Called at render time over the prompt, the action label, and every signpost label
    so a violating string can never leave the engine, and used by the guard test over
    all governed copy. Accepts several strings so one call covers a whole rendered
    alert.
    """
    for text in texts:
        found = find_prohibited_words(text)
        if found:
            raise ProhibitedWordError(
                "Alert content contains prohibited clinical words "
                f"{found!r}: alerts signpost community and statutory support only "
                "(Product.md section 4.9)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
