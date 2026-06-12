"""Shared-Child sharing (Docs/FeatureDecisions.md, the Shared-Child REFINE entry).

The GOVERNED user-facing copy and its guard for the Shared-Child MVP: a Coordinator
shares a care recipient's Continuity Card (the visibility CEILING, refinement 1) with
another person as a read-only viewer, with first-class recorded consent (refinement 5)
and a warm, capacity-framed surface that never exposes the internal role names
(refinement 7).

This package holds COPY + the guard only (the pure, string-shaping layer). The
persistence and scoping (mint/redeem/roster/revoke, the consent-gated share) live in
app/services/sharing.py over the 0015 substrate RPCs + the 0016 functions; the HTTP
surface is app/routes/sharing.py.

Layout:
  copy.py    GOVERNED COPY: the invite line, the linked-state line, the per-recipient
             consent text (recorded verbatim), the roster labels, plus the copy keys
             the api returns. Strings only; every one guarded at build.
  guard.py   the sharing guard: PROHIBITED_WORDS (the shared clinical list PLUS the
             surveillance + role-label bans) + assert_clean, enforced at build time and
             by the permanent guard test (tests/test_engine_sharing_guard.py).

Module file: HardRules/Api/Modules/Sharing.md.
"""

from app.engines.sharing.copy import (
    ADULT_BLOCKED_COPY_KEY,
    CONSENT_COPY_KEY_ADULT,
    CONSENT_COPY_KEY_CHILD,
    COPY_KEYS,
    INVITE_COPY_KEY,
    LINKED_COPY_KEY,
    REVOKED_COPY_KEY,
    ROSTER_EMPTY_COPY_KEY,
    ROSTER_TITLE_COPY_KEY,
    adult_blocked,
    all_emitted_strings,
    consent_copy_key,
    consent_text,
    invite_intro,
    linked_intro,
    revoked_confirm,
    roster_empty,
    roster_title,
)
from app.engines.sharing.guard import (
    CLINICAL_PROHIBITED_WORDS,
    PROHIBITED_WORDS,
    SHARING_PROHIBITED_WORDS,
    SharingCopyError,
    assert_clean,
    find_prohibited_words,
)

__all__ = [
    # copy
    "consent_text",
    "consent_copy_key",
    "invite_intro",
    "linked_intro",
    "roster_title",
    "roster_empty",
    "revoked_confirm",
    "adult_blocked",
    "all_emitted_strings",
    "COPY_KEYS",
    "CONSENT_COPY_KEY_CHILD",
    "CONSENT_COPY_KEY_ADULT",
    "INVITE_COPY_KEY",
    "LINKED_COPY_KEY",
    "ROSTER_TITLE_COPY_KEY",
    "ROSTER_EMPTY_COPY_KEY",
    "REVOKED_COPY_KEY",
    "ADULT_BLOCKED_COPY_KEY",
    # guard
    "PROHIBITED_WORDS",
    "CLINICAL_PROHIBITED_WORDS",
    "SHARING_PROHIBITED_WORDS",
    "SharingCopyError",
    "assert_clean",
    "find_prohibited_words",
]
