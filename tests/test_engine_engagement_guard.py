"""The PERMANENT prohibited-words guard test for the per-chapter ENGAGEMENT signal.

The engagement signal (the owner's "disengagement" Tier-1 idea, owner-track Task 12; the
researcher + psychiatrist boards' HONEST shape) shows a calm "Quiet" / "Resting" band on a
chapter's own card when it has gone a while without a prepared plan. Its copy is GOVERNED:
every emitted string must be FACTUAL about the plan record (never the carer as the subject of
a failure), warm, NON-clinical, and free of the shame / deficit / streak register.

This test asserts that NO emitted engagement content (every band label, plus the factual note
and the forward invitation of every surfaced band) contains any prohibited word, where the
prohibited set is the SHARED clinical words (the section 4.9 authority, imported) PLUS the
shame / deficit / streak words. It is non-negotiable and permanent: if a future copy edit
introduces one of these, this test fails and the change does not ship.

The same guard runs at render time (app/engines/engagement/copy.py render_signal calls
guard.assert_clean), so a violating string cannot even leave the engine; this test is the
standing proof over the WHOLE governed surface. It mirrors tests/test_engine_checkin_guard.py.
"""

from __future__ import annotations

import pytest

from app.engines.alerts.guard import PROHIBITED_WORDS as ALERT_CLINICAL_WORDS
from app.engines.engagement import (
    CLINICAL_WORDS,
    PROHIBITED_WORDS,
    SHAME_AND_STREAK_WORDS,
    EngagementBand,
    ProhibitedCopyError,
    all_emitted_strings,
    assert_clean,
    find_prohibited_words,
    render_signal,
)

# The exact governed shame / deficit / streak set (the boards' no-deficit-mechanic condition).
# Pinned here so a change to the constant is a visible, deliberate edit (and still must clear
# the psychiatrist sign-off).
EXPECTED_SHAME_AND_STREAK = (
    "abandoned",
    "dormant",
    "neglected",
    "overdue",
    "behind",
    "failing",
    "slipped",
    "you haven't",
    "you havent",
    "you let",
    "streak",
    "down from",
    "in a row",
)


def test_clinical_words_are_the_shared_section_4_9_authority():
    # The clinical set is IMPORTED from the alert guard, not re-declared: ONE clinical-words
    # authority across the product (no silent drift). So the engagement clinical set IS the
    # alert set, and it is a strict prefix of the full engagement prohibited list.
    assert CLINICAL_WORDS == ALERT_CLINICAL_WORDS
    assert PROHIBITED_WORDS[: len(CLINICAL_WORDS)] == ALERT_CLINICAL_WORDS


def test_shame_and_streak_set_is_exactly_the_governed_words():
    assert tuple(SHAME_AND_STREAK_WORDS) == EXPECTED_SHAME_AND_STREAK


def test_prohibited_set_is_clinical_plus_shame_and_streak():
    assert tuple(PROHIBITED_WORDS) == tuple(CLINICAL_WORDS) + EXPECTED_SHAME_AND_STREAK


def test_no_emitted_engagement_string_contains_a_prohibited_word():
    # The whole governed surface: every band label, and the note + invitation of every surfaced
    # band. This is the standing proof the copy never drifts into clinical or shame language.
    offenders = {
        string: find_prohibited_words(string)
        for string in all_emitted_strings()
        if find_prohibited_words(string)
    }
    assert offenders == {}, f"prohibited words found in engagement copy: {offenders}"


def test_every_surfaced_band_passes_the_guard_at_emit_time():
    # render_signal runs assert_clean internally; if a surfaced band produced a prohibited word
    # it would raise here. NOT_STARTED / ACTIVE surface nothing (None), which is fine.
    for band in EngagementBand:
        render_signal(band)  # must not raise


def test_the_banned_label_words_never_appear():
    # The boards' explicit ban: the words "Dormant" and "Abandoned" must NEVER be in any
    # user-facing string. Belt and braces over the whole surface (they are also in the guard).
    for string in all_emitted_strings():
        lowered = string.lower()
        assert "dormant" not in lowered, string
        assert "abandoned" not in lowered, string


@pytest.mark.parametrize("word", EXPECTED_SHAME_AND_STREAK)
def test_each_shame_or_streak_word_is_caught(word):
    # The guard is not vacuous for the shame / streak register: a string containing each word is
    # rejected, case-insensitively.
    assert word in find_prohibited_words(f"This chapter is {word.upper()} now.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"a line with {word} in it")


@pytest.mark.parametrize("word", ALERT_CLINICAL_WORDS)
def test_each_clinical_word_is_caught(word):
    # The guard is not vacuous for the clinical register either (the shared section 4.9 set).
    assert word in find_prohibited_words(f"This mentions {word.upper()} explicitly.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"contains {word} here")


def test_clean_factual_text_passes_the_guard():
    # The safe register (factual about the plan record, warm forward invitation) is clean.
    factual = "No plan prepared here in over 4 weeks. That is completely okay."
    assert find_prohibited_words(factual) == []
    assert find_prohibited_words("Want to prepare for something?") == []
    assert_clean("Quiet", "Resting", "Here whenever you're ready.")  # must not raise


def test_the_carer_is_never_the_subject_of_a_failure_sentence():
    # The "you haven't" / "you let" phrasings (the carer as the subject of a failure) are
    # caught, so a future edit cannot reintroduce blame framing.
    with pytest.raises(ProhibitedCopyError):
        assert_clean("You haven't prepared anything here")
    with pytest.raises(ProhibitedCopyError):
        assert_clean("You let this chapter go quiet")


def test_no_count_or_streak_framing_on_the_gap():
    # The deficit / comparison mechanics the boards rejected ("streak", "down from", "in a row")
    # are caught, so the gap can never be turned into a count or a trend.
    for phrase in ("a 3 week streak", "down from last month", "quiet 3 weeks in a row"):
        with pytest.raises(ProhibitedCopyError):
            assert_clean(phrase)


def test_surfaced_bands_carry_a_factual_note_and_a_warm_invitation():
    # The two surfaced bands each carry the label + note + invitation; NOT_STARTED / ACTIVE
    # surface nothing. This pins the shape of the governed signal.
    for band in (EngagementBand.QUIET, EngagementBand.RESTING):
        content = render_signal(band)
        assert content is not None
        assert content.label  # a short status word
        assert content.note  # a factual line about the plan record
        assert content.invitation  # a warm forward door
    assert render_signal(EngagementBand.NOT_STARTED) is None
    assert render_signal(EngagementBand.ACTIVE) is None
