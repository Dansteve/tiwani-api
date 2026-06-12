"""The non-clinical, non-surveillance guard for Shared-Child user-facing copy.

TIWANI stores participation-planning data only and is non-clinical infrastructure
(root CLAUDE.md). The Shared-Child sharing copy (the invite line, the linked-state
line, the consent text, the roster labels) is shown to a Coordinator and to the
person they share with, so it carries an EXTRA bar on top of the clinical one
(Docs/FeatureDecisions.md, the Shared-Child REFINE entry, refinement 7): it must be
warm and capacity-framed, must use NO clinical vocabulary, NO surveillance vocabulary
("case", "subject", "monitor", "track", "surveillance"), and must NEVER expose the
internal RBAC role names ("viewer" / "owner") as user-facing labels.

This module is the single definition of the prohibited words for the sharing surface
and the guard that enforces the rule on every emitted string. The clinical-words list
is the SAME governed list the alerts/cards guard owns (app/engines/alerts/guard.py);
we reuse it verbatim rather than re-declare it, so there is one clinical-words
authority. This module ADDS the surveillance + role-label bans that are specific to
the sharing surface.

The constraint is the product, not a preference: if a future copy edit needs one of
these words it does not ship. A permanent guard test
(tests/test_engine_sharing_guard.py) asserts none of these strings ever appears in
ANY emitted sharing copy, and assert_clean() is also called at copy-build time so a
violating string can never leave the module.
"""

from __future__ import annotations

from typing import Iterable

# The clinical-words authority is shared: reuse the alerts/cards list verbatim (one
# definition, one place). Re-exported here so a reader sees the full prohibited surface
# the sharing guard enforces.
from app.engines.alerts.guard import (
    PROHIBITED_WORDS as CLINICAL_PROHIBITED_WORDS,
)
from app.engines.alerts.guard import (
    find_prohibited_words as _find_clinical_words,
)

# The surveillance / role-label words PROHIBITED in Shared-Child copy ON TOP of the
# clinical list (refinement 7). Matched case-insensitively as substrings, with a word
# boundary check (below) so a banned token does not falsely catch an innocent word that
# merely contains it. This is the exact governed addition for the sharing surface; do
# not add, remove, or soften an entry without the product owner and the psychiatrist
# sign-off (Task 12).
#
#   case / subject  : the share is between PEOPLE who care for someone, never a "case"
#                     or a "subject" (clinical/case-management framing the product bars).
#   monitor / track / surveillance : the product is participation planning, not
#                     watching; a person shared-with is helping, not monitoring.
#   viewer / owner  : the internal RBAC role NAMES (recipient_membership.role). They are
#                     correct in the schema and the code, but they must NEVER surface as
#                     a user-facing label (the copy says "people who can see [name]'s
#                     card", "you can manage who can see it", not "viewers" / "the owner").
SHARING_PROHIBITED_WORDS = (
    "case",
    "subject",
    "monitor",
    "track",
    "surveillance",
    "viewer",
    "owner",
)

# The full prohibited surface for the sharing copy: the clinical authority PLUS the
# sharing-specific bans. Order is clinical-first, then the sharing additions, so a
# reported offender keeps a stable, readable order.
PROHIBITED_WORDS = tuple(CLINICAL_PROHIBITED_WORDS) + SHARING_PROHIBITED_WORDS


class SharingCopyError(ValueError):
    """Raised when emitted Shared-Child copy contains a prohibited word.

    A programming/governance error, never a runtime user error: it means an invite,
    linked-state, consent, or roster string broke the non-clinical / non-surveillance /
    no-role-label constraint and must be fixed before it can ship. Surfaced loudly (an
    exception) rather than silently scrubbed.
    """


def _contains_word(haystack: str, needle: str) -> bool:
    """True if `needle` appears in `haystack` as a whole word (case-insensitive).

    A whole-word (boundary) match, NOT a bare substring: it stops a banned token from
    falsely catching an innocent longer word that merely contains it (e.g. "subject"
    must not trip on "subjective"-free copy, "track" must not trip on a word that does
    not exist in this copy, and crucially "owner" must catch the standalone role label
    but not be defeated by punctuation). A character is part of a word if it is a letter
    or digit; the needle matches when the characters on each side of an occurrence are
    NOT word characters (or the string edge). Used ONLY for the sharing-specific additions
    (case/subject/monitor/track/surveillance/viewer/owner); the clinical entries are matched
    by the canonical alert-guard SUBSTRING matcher instead (see find_prohibited_words), so the
    clinical bar is identical to the alert surface.
    """
    h = haystack.lower()
    n = needle.lower()
    start = 0
    while True:
        idx = h.find(n, start)
        if idx == -1:
            return False
        before = h[idx - 1] if idx > 0 else ""
        after_idx = idx + len(n)
        after = h[after_idx] if after_idx < len(h) else ""
        if not before.isalnum() and not after.isalnum():
            return True
        start = idx + 1


def find_prohibited_words(text: str) -> list[str]:
    """The prohibited words present in `text`, clinical-first then the sharing additions.

    The CLINICAL entries are matched with the canonical alert-guard SUBSTRING matcher
    (app.engines.alerts.guard.find_prohibited_words), so the clinical bar on the sharing
    surface is byte-for-byte the SAME bar as on the alert surface: "clinically",
    "treatments", "conditioned" are caught here exactly as they are there (one list, one
    matcher). The sharing-specific additions (the surveillance + role-label words) use the
    whole-word matcher so a banned token does not falsely catch an innocent longer word.
    Empty list means the text is clean for the sharing surface.
    """
    clinical = _find_clinical_words(text)
    sharing = [word for word in SHARING_PROHIBITED_WORDS if _contains_word(text, word)]
    return clinical + sharing


def assert_clean(*texts: str) -> None:
    """Raise SharingCopyError if any of the given strings contains a prohibited word.

    Called at copy-build time over every emitted sharing string (the invite line, the
    linked-state line, the consent text, the roster labels) so a violating string can
    never leave the module, and used by the guard test over all governed copy. Accepts
    several strings so one call covers a whole rendered surface.
    """
    for text in texts:
        found = find_prohibited_words(text)
        if found:
            raise SharingCopyError(
                "Shared-Child copy contains prohibited words "
                f"{found!r}: the sharing surface is warm, non-clinical, non-surveillance, "
                "and never exposes the internal role names (Docs/FeatureDecisions.md, the "
                "Shared-Child REFINE entry, refinement 7)."
            )


def assert_all_clean(texts: Iterable[str]) -> None:
    """assert_clean over an iterable (the guard test feeds it every emitted string)."""
    assert_clean(*list(texts))
