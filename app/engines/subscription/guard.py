"""The governed guard for paywall / subscription COPY.

TIWANI is non-clinical infrastructure and a feature that protects a vulnerable
person must never be SOLD with fear, guilt, or a clinical or outcome claim
(root CLAUDE.md; Docs/FeatureDecisions.md, the Subscription paywall-copy
refinement). The subscription work itself is DEFERRED behind six hard
preconditions, but the refinement isolates one piece that is buildable and
testable on its own: the paywall copy is a GOVERNED module with a guard test,
exactly like the Erosion Alert copy.

This guard is the single definition of what paywall copy may NOT say. It is
STRICTER than the alert guard, not a replacement: it REUSES the shared
non-clinical word list (app/engines/alerts/guard.py PROHIBITED_WORDS, imported,
never re-typed) so the clinical bar stays one list, and it ADDS the four banned
families the refinement names:

  1. CLINICAL words (the shared alert list: symptoms, diagnosis, ... therapy).
  2. CHILD-PROTECTION framing: "protect", "keep [name] safe", "safer",
     "at risk". A paywall must not imply paying makes the child safer.
  3. EFFICACY / OUTCOME claims: "better continuity", "more stable", "improve".
     A convenience tier buys conveniences, never a better outcome for the child.
  4. GUILT / URGENCY / SCARCITY: "before it's too late", countdowns,
     "you've reached your limit". No pressure, no manufactured scarcity.

The constraint is the product, not a preference: if a future paywall string
needs one of these concepts it does not ship. The permanent guard test
(tests/test_engine_subscription_guard.py) asserts NONE of these ever appears in
ANY emitted paywall string, and assert_clean() is called at render time so a
violating string can never leave the module.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

# The clinical word list is OWNED by the alert guard; reuse it, do not fork it, so
# the non-clinical bar is one governed list across the whole product (the same
# reuse the seed guard and the card builder make). assert_clean below runs the
# clinical check by delegating to find_prohibited_words / the shared list.
from app.engines.alerts.guard import (
    PROHIBITED_WORDS as CLINICAL_WORDS,
)
from app.engines.alerts.guard import (
    find_prohibited_words as _find_clinical_words,
)

# --- the four extra banned families (Docs/FeatureDecisions.md, the refinement) ---
# Each entry is a verbatim banned PHRASE, matched case-insensitively as a substring
# (so "Protect" and "PROTECT" are caught as well as "protect"). The lists are the
# governed set; an entry is not added, removed, or softened without the product
# owner AND the psychiatrist sign-off (the same gate the alert guard carries).

# 2. Child-protection / safeguarding framing. A paywall must never imply that paying
#    protects the child or that not paying leaves them less safe. "[name]" stands for
#    the templated recipient name in the refinement's "keep [name] safe" example; both
#    the literal token and the bare verb/adjective forms are barred so no rendered
#    name can reconstitute the framing.
PROTECTION_WORDS: Tuple[str, ...] = (
    "protect",
    "keep them safe",
    "keep [name] safe",
    "keep your child safe",
    "safer",
    "at risk",
    "safeguard",
)

# 3. Efficacy / outcome claims. A convenience tier may not claim it produces a better
#    care outcome (better continuity, more stability, improvement); the LCI/alerts are
#    identical on every tier and no paid feature is a new measurement or outcome claim.
EFFICACY_WORDS: Tuple[str, ...] = (
    "better continuity",
    "more stable",
    "more stability",
    "improve",
    "improved",
    "better outcome",
    "better results",
    "more effective",
)

# 4. Guilt / urgency / scarcity. No fear of missing out, no countdown, no "you have hit
#    a wall" shaming, no manufactured deadline. The refinement names these three.
URGENCY_WORDS: Tuple[str, ...] = (
    "before it's too late",
    "before it is too late",
    "don't miss out",
    "do not miss out",
    "act now",
    "hurry",
    "last chance",
    "limited time",
    "offer ends",
    "countdown",
    "you've reached your limit",
    "you have reached your limit",
    "you've hit your limit",
    "running out",
)

# The full banned set as ordered (family, words) groups, so a caller (and the guard
# test) can report WHICH family a violation came from, and pin each family exactly.
BANNED_FAMILIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("clinical", tuple(CLINICAL_WORDS)),
    ("child_protection", PROTECTION_WORDS),
    ("efficacy", EFFICACY_WORDS),
    ("urgency_scarcity", URGENCY_WORDS),
)

# The flat tuple of every banned phrase, in family order, for the simple "is this one
# string clean" path and for parametrized tests.
BANNED_PHRASES: Tuple[str, ...] = tuple(
    phrase for _family, words in BANNED_FAMILIES for phrase in words
)


class PaywallCopyError(ValueError):
    """Raised when paywall copy contains a banned phrase.

    A governance error, never a runtime user error: it means a paywall string
    broke the calm, non-clinical, no-pressure constraint and must be fixed before
    it can ship. Surfaced loudly (an exception), never silently scrubbed, so a bad
    string cannot leave the module.
    """


def find_banned_phrases(text: str) -> List[Tuple[str, str]]:
    """The banned (family, phrase) pairs present in `text` (case-insensitive substring).

    Returns each banned entry that appears, in BANNED_FAMILIES order, so a caller or
    the guard test can report exactly what was found and from which family. The
    clinical family is checked through the SHARED alert helper (the one list), the
    other three against this module's lists. Empty list means the text is clean.
    """
    found: List[Tuple[str, str]] = []
    # Clinical: delegate to the shared list so there is exactly one clinical check.
    for word in _find_clinical_words(text):
        found.append(("clinical", word))
    lowered = text.lower()
    for family, words in BANNED_FAMILIES:
        if family == "clinical":
            continue
        for phrase in words:
            if phrase in lowered:
                found.append((family, phrase))
    return found


def assert_clean(*texts: str) -> None:
    """Raise PaywallCopyError if any given string contains a banned phrase.

    Called at render time over every emitted paywall string so a violating string
    can never leave the module, and used by the guard test over all governed copy.
    Accepts several strings so one call can cover a whole rendered paywall message.
    """
    for text in texts:
        found = find_banned_phrases(text)
        if found:
            raise PaywallCopyError(
                "Paywall copy contains banned phrases "
                f"{found!r}: paywall copy is calm and capacity-framed, with no "
                "clinical words, no child-protection framing, no efficacy or "
                "outcome claim, and no guilt, urgency, or scarcity "
                "(Docs/FeatureDecisions.md, the Subscription paywall-copy refinement)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
