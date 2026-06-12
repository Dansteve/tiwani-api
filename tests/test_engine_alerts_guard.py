"""The PERMANENT prohibited-words guard test for Erosion Alert copy (section 4.9).

TIWANI is non-clinical infrastructure: alert copy may only signpost COMMUNITY and
statutory support and must NEVER use clinical vocabulary (root CLAUDE.md, Product.md
section 4.9). This test asserts that NO emitted alert content, across every chapter
and every level (each prompt, every action label, and every signpost label), contains
any prohibited word. It is non-negotiable and permanent: if a future copy edit
introduces one of these words, this test fails and the change does not ship.

The same guard runs at render time (app/engines/alerts/copy.py render_alert calls
guard.assert_clean), so a violating string cannot even leave the engine; this test is
the standing proof over the WHOLE governed surface.
"""

from __future__ import annotations

import pytest

from app.engines.alerts import (
    PROHIBITED_WORDS,
    ProhibitedWordError,
    all_emitted_strings,
    find_prohibited_words,
    render_alert,
)
from app.engines.alerts.evaluation import AlertLevel
from app.engines.alerts.guard import assert_clean
from app.models.chapters import Chapter

# The exact governed prohibited list (Product.md section 4.9). Pinned here so a change
# to the constant is a visible, deliberate edit (and still must clear sign-off).
EXPECTED_PROHIBITED = (
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


def test_prohibited_word_list_is_exactly_the_governed_set():
    assert tuple(PROHIBITED_WORDS) == EXPECTED_PROHIBITED


def test_no_emitted_alert_string_contains_a_prohibited_word():
    # The whole governed surface: every chapter x level prompt, every action label,
    # every signpost label.
    offenders = {
        string: find_prohibited_words(string)
        for string in all_emitted_strings()
        if find_prohibited_words(string)
    }
    assert offenders == {}, f"prohibited clinical words found in alert copy: {offenders}"


def test_every_rendered_alert_passes_the_guard_at_emit_time():
    # render_alert runs assert_clean internally; if any chapter/level produced a
    # prohibited word it would raise here.
    for chapter in Chapter:
        for level in AlertLevel:
            render_alert(chapter, level)  # must not raise


@pytest.mark.parametrize("word", EXPECTED_PROHIBITED)
def test_each_prohibited_word_is_actually_caught_by_the_guard(word):
    # The guard is not vacuous: a string containing each prohibited word is rejected,
    # case-insensitively.
    assert find_prohibited_words(f"This mentions {word.upper()} explicitly.") == [word]
    with pytest.raises(ProhibitedWordError):
        assert_clean(f"contains {word} here")


def test_clean_text_passes_the_guard():
    assert find_prohibited_words("Carers UK and ACAS workplace rights guidance") == []
    assert_clean("Review support options", "Find support")  # must not raise
