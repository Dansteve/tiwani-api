"""The PERMANENT prohibited-words guard test for Shared-Child user-facing copy.

The Shared-Child sharing copy (the invite line, the linked-state line, the recorded
consent text, the roster labels) is shown to a Coordinator and to the person they share
with, so it carries an EXTRA bar on top of the clinical one (Docs/FeatureDecisions.md,
the Shared-Child REFINE entry, refinement 7): warm and capacity-framed, NO clinical
vocabulary, NO surveillance vocabulary ("case", "subject", "monitor", "track",
"surveillance"), and NEVER the internal RBAC role names ("viewer" / "owner") as a
user-facing label.

This test asserts that NO emitted sharing string contains any prohibited word, that the
guard is non-vacuous (each prohibited word IS caught), and that the whole-word match
does not falsely trip on innocent longer words. It mirrors
tests/test_engine_alerts_guard.py and is non-negotiable and permanent: if a future copy
edit introduces one of these words, this test fails and the change does not ship.

assert_clean() also runs at copy-build time (every function in app/engines/sharing/copy.py
guards its output), so a violating string cannot even leave the module; this test is the
standing proof over the WHOLE governed sharing surface.
"""

from __future__ import annotations

import pytest

from app.engines.sharing import (
    PROHIBITED_WORDS,
    SharingCopyError,
    all_emitted_strings,
    find_prohibited_words,
)
from app.engines.sharing.copy import (
    adult_blocked,
    consent_text,
    invite_intro,
    linked_intro,
    revoked_confirm,
    roster_empty,
    roster_title,
)
from app.engines.sharing.guard import (
    CLINICAL_PROHIBITED_WORDS,
    SHARING_PROHIBITED_WORDS,
    assert_clean,
)

# The exact sharing-specific additions (the surveillance + role-label bans). Pinned here
# so a change to the constant is a visible, deliberate edit (and still must clear sign-off).
EXPECTED_SHARING_ADDITIONS = (
    "case",
    "subject",
    "monitor",
    "track",
    "surveillance",
    "viewer",
    "owner",
)

# The clinical authority the sharing guard reuses (Product.md section 4.9). The sharing
# guard must not silently drop any clinical word.
EXPECTED_CLINICAL = (
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


def test_sharing_additions_are_exactly_the_governed_set():
    assert tuple(SHARING_PROHIBITED_WORDS) == EXPECTED_SHARING_ADDITIONS


def test_sharing_guard_reuses_the_clinical_authority_verbatim():
    # The clinical list is the shared one, not re-declared; the full prohibited set is the
    # clinical authority PLUS the sharing additions.
    assert tuple(CLINICAL_PROHIBITED_WORDS) == EXPECTED_CLINICAL
    assert tuple(PROHIBITED_WORDS) == EXPECTED_CLINICAL + EXPECTED_SHARING_ADDITIONS


def test_clinical_suffix_forms_are_caught_on_the_sharing_surface():
    # N1 (psychiatrist review): clinical words use the SAME substring matcher as the alert
    # guard, so suffixed forms that a whole-word matcher would miss are caught here too. The
    # clinical bar on the sharing surface is byte-for-byte the alert-surface bar.
    assert "clinical" in find_prohibited_words("the room is clinically lit")
    assert "treatment" in find_prohibited_words("we discussed treatments")
    assert "condition" in find_prohibited_words("an air-conditioned room")
    # The surveillance / role-label additions keep the whole-word matcher: an innocent longer
    # word that merely contains one is NOT a false positive.
    assert find_prohibited_words("that was a subjective view") == []


def test_no_emitted_sharing_string_contains_a_prohibited_word():
    # The whole governed surface: every governed string in both the named and the
    # neutral-fallback forms (all_emitted_strings renders both).
    offenders = {
        string: find_prohibited_words(string)
        for string in all_emitted_strings()
        if find_prohibited_words(string)
    }
    assert offenders == {}, f"prohibited words found in sharing copy: {offenders}"


def test_every_governed_builder_passes_the_guard_at_emit_time():
    # Each builder runs assert_clean internally; a prohibited word would raise here. Render
    # each with a real first name and the empty (fallback) name.
    for name in ("Ade", ""):
        consent_text(name, subject_kind="child")
        consent_text(name, subject_kind="adult")
        invite_intro(name)
        linked_intro(name)
        roster_title(name)
        roster_empty(name)
        revoked_confirm(name)
        adult_blocked(name)  # must not raise


@pytest.mark.parametrize("word", EXPECTED_SHARING_ADDITIONS + EXPECTED_CLINICAL)
def test_each_prohibited_word_is_actually_caught_by_the_guard(word):
    # The guard is not vacuous: a string containing each prohibited word (as a whole word)
    # is rejected, case-insensitively.
    assert find_prohibited_words(f"This mentions {word.upper()} explicitly.") == [word]
    with pytest.raises(SharingCopyError):
        assert_clean(f"contains {word} here")


def test_whole_word_match_does_not_trip_on_innocent_longer_words():
    # The boundary match must not flag a word that merely CONTAINS a banned token:
    #  - "subjective" contains "subject" but is not the banned standalone word,
    #  - "tracker"/"tracking" contains "track" (we still ban the standalone "track"),
    #  - "owned"/"owners" vs the standalone role label "owner".
    # The guard bans the standalone tokens; these longer words are clean.
    assert find_prohibited_words("a subjective, ownerless tracking-free note") == []
    # But the standalone banned words are still caught.
    assert find_prohibited_words("the owner will track this case") == ["case", "track", "owner"]


def test_clean_capacity_framed_text_passes_the_guard():
    assert find_prohibited_words("People who can see Ade's support card") == []
    assert_clean(
        "You can change or stop their access whenever you like",
        "The family keeps it up to date",
    )  # must not raise
