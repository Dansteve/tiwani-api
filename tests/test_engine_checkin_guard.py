"""The PERMANENT prohibited-words guard test for the carer check-in moment.

The check-in moment ("A moment for you", ProductReview.md item 9, the psychiatrist board's
SAFE shape) is OPTIONAL, signpost-only, and EPHEMERAL: it acknowledges the carer and points
to real support, it NEVER scores the carer, and it stores nothing. Its copy is GOVERNED:
every emitted string must be warm, honest, NON-clinical, and free of the hollow-affirmation
register (the owner's "return motivation" shape was rejected as hollow).

This test asserts that NO emitted moment content, across every tap branch (the intro, every
tap label, each acknowledgement, and every signpost label), contains any prohibited word,
where the prohibited set is the SHARED clinical words (the section 4.9 authority, imported)
PLUS the hollow-affirmation phrases. It is non-negotiable and permanent: if a future copy
edit introduces one of these, this test fails and the change does not ship.

The same guard runs at render time (app/engines/checkin/copy.py render_moment calls
guard.assert_clean), so a violating string cannot even leave the engine; this test is the
standing proof over the WHOLE governed surface. It mirrors tests/test_engine_alerts_guard.py.
"""

from __future__ import annotations

import pytest

from app.engines.alerts.guard import PROHIBITED_WORDS as ALERT_CLINICAL_WORDS
from app.engines.checkin import (
    CLINICAL_WORDS,
    HOLLOW_AFFIRMATION_WORDS,
    PROHIBITED_WORDS,
    MomentTap,
    ProhibitedCopyError,
    all_emitted_strings,
    assert_clean,
    find_prohibited_words,
    render_moment,
)
from app.engines.checkin.copy import _CRISIS_SIGNPOSTS, _SAMARITANS

# The exact governed hollow-affirmation set (the psychiatrist's rejection of "return
# motivation"). Pinned here so a change to the constant is a visible, deliberate edit (and
# still must clear the psychiatrist + DPO sign-off).
EXPECTED_HOLLOW_AFFIRMATION = (
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


def test_clinical_words_are_the_shared_section_4_9_authority():
    # The clinical set is IMPORTED from the alert guard, not re-declared: ONE clinical-words
    # authority across the product (no silent drift). So the check-in clinical set IS the
    # alert set, and it is a strict prefix of the full check-in prohibited list.
    assert CLINICAL_WORDS == ALERT_CLINICAL_WORDS
    assert PROHIBITED_WORDS[: len(CLINICAL_WORDS)] == ALERT_CLINICAL_WORDS


def test_hollow_affirmation_set_is_exactly_the_governed_phrases():
    assert tuple(HOLLOW_AFFIRMATION_WORDS) == EXPECTED_HOLLOW_AFFIRMATION


def test_prohibited_set_is_clinical_plus_hollow_affirmation():
    assert tuple(PROHIBITED_WORDS) == tuple(CLINICAL_WORDS) + EXPECTED_HOLLOW_AFFIRMATION


def test_no_emitted_moment_string_contains_a_prohibited_word():
    # The whole governed surface: the intro, every tap label, each branch acknowledgement,
    # and every signpost label, across every tap branch.
    offenders = {
        string: find_prohibited_words(string)
        for string in all_emitted_strings()
        if find_prohibited_words(string)
    }
    assert offenders == {}, f"prohibited words found in check-in moment copy: {offenders}"


def test_every_rendered_branch_passes_the_guard_at_emit_time():
    # render_moment runs assert_clean internally; if any branch produced a prohibited word
    # it would raise here.
    for tap in MomentTap:
        render_moment(tap)  # must not raise


@pytest.mark.parametrize("word", EXPECTED_HOLLOW_AFFIRMATION)
def test_each_hollow_affirmation_phrase_is_caught(word):
    # The guard is not vacuous for the hollow-affirmation register: a string containing each
    # phrase is rejected, case-insensitively.
    assert word in find_prohibited_words(f"Just remember, {word.upper()} today.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"a line with {word} in it")


@pytest.mark.parametrize("word", ALERT_CLINICAL_WORDS)
def test_each_clinical_word_is_caught(word):
    # The guard is not vacuous for the clinical register either (the shared section 4.9 set).
    assert word in find_prohibited_words(f"This mentions {word.upper()} explicitly.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"contains {word} here")


def test_clean_supportive_text_passes_the_guard():
    assert find_prohibited_words("You do not have to manage this alone. Carers UK can help.") == []
    assert_clean("A moment for you", "Doing okay", "Hard day")  # must not raise


def test_hard_branch_carries_the_crisis_capable_carer_route():
    # The psychiatrist's condition 5: a hard-day answer must include a crisis-capable carer
    # route (talk to someone TODAY). The Samaritans 116 123 route is the lead crisis signpost
    # and must be present on the HARD branch.
    hard = render_moment(MomentTap.HARD)
    labels = [s.label for s in hard.signposts]
    assert _SAMARITANS in _CRISIS_SIGNPOSTS
    assert any("116 123" in label for label in labels), labels
    assert any("111" in label for label in labels), labels
    # And the whole crisis-capable set leads the hard branch.
    assert hard.signposts[: len(_CRISIS_SIGNPOSTS)] == _CRISIS_SIGNPOSTS


def test_acknowledgements_are_supportive_not_affirming_across_branches():
    # Every branch acknowledgement is clean (no clinical / hollow-affirmation word) and the
    # hard branch carries the section 4.9 L3 register ("you do not have to manage this alone").
    for tap in MomentTap:
        content = render_moment(tap)
        assert find_prohibited_words(content.acknowledgement) == []
    assert "do not have to manage this alone" in render_moment(MomentTap.HARD).acknowledgement
