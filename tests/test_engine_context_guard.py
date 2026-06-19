"""The PERMANENT prohibited-words guard test for the display-only calendar context layer.

The calendar context (FeatureDecisions.md 2026-06-19, the Real-World Context Layer Part B)
overlays public calendar dates on the check-in history. Its copy is GOVERNED and
decline-adjacent: every emitted string must be a WORLD-FACT (a date), NON-clinical, and free
of the editorialising / causal register (never a verdict on the check-in signal, never a
claim of cause).

This test asserts that NO emitted context content (the intro, the hedge, and every window
note) contains any prohibited word, where the prohibited set is the SHARED clinical words
(the section 4.9 authority, imported) PLUS the editorialising / causal words. It is the
standing proof the panel's "world-facts only" condition holds over the whole surface; the
same guard runs at render time (copy.render_window_note calls assert_clean), so a violating
string cannot even leave the engine. It mirrors tests/test_engine_engagement_guard.py.
"""

from __future__ import annotations

import pytest

from app.engines.alerts.guard import PROHIBITED_WORDS as ALERT_CLINICAL_WORDS
from app.engines.context import (
    ALL_WINDOWS,
    CALENDAR_HEDGE,
    CALENDAR_INTRO,
    CLINICAL_WORDS,
    EDITORIALISING_WORDS,
    PROHIBITED_WORDS,
    ProhibitedCopyError,
    all_emitted_strings,
    assert_clean,
    find_prohibited_words,
    render_window_note,
)

# The exact governed editorialising / causal set (the panel's anti-masking condition).
# Pinned here so a change to the constant is a visible, deliberate edit (and still must
# clear the psychiatrist sign-off).
EXPECTED_EDITORIALISING = (
    "seasonal",
    "normal",
    "nothing to worry",
    "no need to worry",
    "don't worry",
    "dont worry",
    "as expected",
    "to be expected",
    "reassur",
    "because",
    "due to",
    "caused by",
    "explained by",
    "explains",
    "thanks to",
    "probably",
    "likely",
)


def test_clinical_words_are_the_shared_section_4_9_authority():
    # The clinical set is IMPORTED from the alert guard, not re-declared: ONE clinical-words
    # authority across the product (no silent drift). So the context clinical set IS the
    # alert set, and it is a strict prefix of the full context prohibited list.
    assert CLINICAL_WORDS == ALERT_CLINICAL_WORDS
    assert PROHIBITED_WORDS[: len(CLINICAL_WORDS)] == ALERT_CLINICAL_WORDS


def test_editorialising_set_is_exactly_the_governed_words():
    assert tuple(EDITORIALISING_WORDS) == EXPECTED_EDITORIALISING


def test_prohibited_set_is_clinical_plus_editorialising():
    assert tuple(PROHIBITED_WORDS) == tuple(CLINICAL_WORDS) + EXPECTED_EDITORIALISING


def test_no_emitted_context_string_contains_a_prohibited_word():
    # The whole governed surface: the intro, the hedge, and every window note. The standing
    # proof the copy never drifts into clinical, verdict, or causal language.
    offenders = {
        string: find_prohibited_words(string)
        for string in all_emitted_strings()
        if find_prohibited_words(string)
    }
    assert offenders == {}, f"prohibited words found in calendar context copy: {offenders}"


def test_every_window_note_passes_the_guard_at_emit_time():
    # render_window_note runs assert_clean internally; if any window produced a prohibited
    # word it would raise here.
    for window in ALL_WINDOWS:
        render_window_note(window)  # must not raise


@pytest.mark.parametrize("word", EXPECTED_EDITORIALISING)
def test_each_editorialising_word_is_caught(word):
    # The guard is not vacuous for the editorialising / causal register: a string containing
    # each word is rejected, case-insensitively.
    assert word in find_prohibited_words(f"This note {word.upper()} here.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"a line with {word} in it")


@pytest.mark.parametrize("word", ALERT_CLINICAL_WORDS)
def test_each_clinical_word_is_caught(word):
    # The guard is not vacuous for the clinical register either (the shared section 4.9 set).
    assert word in find_prohibited_words(f"This mentions {word.upper()} explicitly.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"contains {word} here")


def test_clean_world_fact_text_passes_the_guard():
    # The safe register (a public date, the governed intro + hedge) is clean.
    assert find_prohibited_words(CALENDAR_INTRO) == []
    assert find_prohibited_words(CALENDAR_HEDGE) == []
    assert_clean("Summer bank holiday, 25 August 2025.")  # must not raise
    assert_clean("Summer holidays (England state schools, approximate): "
                 "23 July 2025 to 1 September 2025.")  # must not raise


def test_a_verdict_on_the_signal_is_rejected():
    # The masking failure the panel rejected: the context must never interpret the dip.
    for phrase in (
        "This dip is seasonal.",
        "Nothing to worry about, it was the holidays.",
        "This is normal for the summer.",
        "The quiet stretch is to be expected.",
    ):
        with pytest.raises(ProhibitedCopyError):
            assert_clean(phrase)


def test_a_causal_claim_is_rejected():
    # The context reports a world-fact; it never claims a cause for the check-ins.
    for phrase in (
        "The dip happened because of the holidays.",
        "Lower activity due to the school break.",
        "This was caused by the rail strike.",
        "The drop is explained by half-term.",
    ):
        with pytest.raises(ProhibitedCopyError):
            assert_clean(phrase)
