"""The Village Delegation Hub engine (Docs/FeatureDecisions.md, the GOVERNED copy).

A closed follow-through loop for a Coordinator's village (family / friends / trusted
helpers) to VOLUNTEER for a specific bounded NEED: need -> claim -> confirm -> done /
dropped, with an auto re-broadcast on a drop. A need belongs to EXACTLY ONE recipient and
is the SECOND consumer of the recipient_membership substrate (migration 0015); the schema
+ the atomic, owner / member-gated RPCs are migration 0017 (PENDING OWNER APPLY).

Module file: HardRules/Api/Modules/Village.md.

This engine package holds the GOVERNED user-facing copy and its guard only (the state
machine + RLS live in migration 0017; the data layer + the friendly-error mapping live in
app/services/village.py; the HTTP surface in app/routes/village.py):
  guard.py  the Hub's non-clinical + non-surveillance + no-role-label guard:
            PROHIBITED_WORDS + assert_clean, enforced at emit time and by the permanent
            guard test (tests/test_engine_village_guard.py).
  copy.py   the GOVERNED copy keyed by stable copy-keys: the need framing, the claim /
            confirm / done / drop confirmations, and the per-recipient consent text. Warm,
            capacity-framed; every string passes the guard.

LAUNCH GATE: the Hub COPY does not ship to beta without psychiatrist sign-off (Task 12),
the same gate as the Erosion Alert copy.
"""

from app.engines.village.copy import (
    COPY,
    RESULT_KEY_BY_ACTION,
    all_emitted_strings,
    consent_text,
    render,
    result_copy_key,
)
from app.engines.village.guard import (
    PROHIBITED_WORDS,
    ProhibitedCopyError,
    assert_all_clean,
    assert_clean,
    find_prohibited_words,
)

__all__ = [
    # copy
    "COPY",
    "RESULT_KEY_BY_ACTION",
    "all_emitted_strings",
    "consent_text",
    "render",
    "result_copy_key",
    # guard
    "PROHIBITED_WORDS",
    "ProhibitedCopyError",
    "assert_all_clean",
    "assert_clean",
    "find_prohibited_words",
]
