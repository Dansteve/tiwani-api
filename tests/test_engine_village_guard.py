"""The PERMANENT governed-copy guard test for the Village Delegation Hub.

Mirrors tests/test_engine_alerts_guard.py (the Village Hub decision, refinement 6). The
Hub's user-facing copy must be WARM and CAPACITY-FRAMED, and must NEVER use clinical
words, NEVER use surveillance / monitoring language ("monitor / track / surveillance /
case / subject", the board's explicit list, refinement 3), and NEVER leak the internal
RBAC role labels ("viewer" / "owner") as user-facing words (refinement, Shared-Child 7
carried into the Hub). This test asserts that NO emitted Hub copy, across every governed
copy-key and the consent text, contains any prohibited word. It is non-negotiable and
permanent: if a future copy edit introduces one of these words, this test fails and the
change does not ship.

The same guard runs at emit time (app/engines/village/copy.py render() calls
guard.assert_clean), so a violating string cannot even leave the engine; this test is the
standing proof over the WHOLE governed surface.
"""

from __future__ import annotations

import pytest

from app.engines.village import (
    COPY,
    PROHIBITED_WORDS,
    ProhibitedCopyError,
    all_emitted_strings,
    consent_text,
    find_prohibited_words,
    render,
)
from app.engines.village.guard import (
    PROHIBITED_SUBSTRINGS,
    PROHIBITED_WORD_BOUNDED,
    assert_clean,
)

# The exact governed prohibited set, pinned so a change to the constant is a visible,
# deliberate edit (and still must clear sign-off). Three categories: clinical words,
# surveillance / monitoring words, and the internal role labels.
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
EXPECTED_SURVEILLANCE_SUBSTRINGS = ("monitor", "surveillance", "track")
EXPECTED_WORD_BOUNDED = ("case", "subject", "viewer", "owner")


def test_prohibited_list_is_exactly_the_governed_set():
    # The substring set is the clinical words + the surveillance substrings; the
    # word-bounded set is case / subject / viewer / owner.
    assert tuple(PROHIBITED_SUBSTRINGS) == EXPECTED_CLINICAL + EXPECTED_SURVEILLANCE_SUBSTRINGS
    assert tuple(PROHIBITED_WORD_BOUNDED) == EXPECTED_WORD_BOUNDED
    # The combined view is everything.
    assert tuple(PROHIBITED_WORDS) == (
        EXPECTED_CLINICAL + EXPECTED_SURVEILLANCE_SUBSTRINGS + EXPECTED_WORD_BOUNDED
    )


def test_clinical_list_is_imported_from_the_alert_guard_not_re_typed():
    # N2 (psychiatrist review): the Hub clinical list must BE the alert guard's governed list
    # (imported), not a hand-typed copy, so a future addition to the Product.md §4.9 list
    # propagates here automatically and cannot silently drift out of date (one clinical-words
    # authority across the product, per root CLAUDE.md).
    from app.engines.alerts.guard import PROHIBITED_WORDS as ALERT_CLINICAL
    from app.engines.village.guard import _CLINICAL_WORDS as VILLAGE_CLINICAL

    assert VILLAGE_CLINICAL is ALERT_CLINICAL, (
        "the Village clinical list must be the imported alert PROHIBITED_WORDS, not a re-typed copy"
    )


def test_no_emitted_hub_string_contains_a_prohibited_word():
    # The whole governed surface: every copy-key rendered with a name and the neutral
    # fallback.
    offenders = {
        string: find_prohibited_words(string)
        for string in all_emitted_strings()
        if find_prohibited_words(string)
    }
    assert offenders == {}, f"prohibited words found in Village Hub copy: {offenders}"


def test_every_copy_key_renders_and_passes_the_guard_at_emit_time():
    # render() runs assert_clean internally; if any key produced a prohibited word it would
    # raise here. Cover both a named and the neutral-fallback render.
    for key in COPY:
        render(key, name="Sam")  # must not raise
        render(key, name="")  # must not raise


def test_consent_text_is_governed_and_clean():
    # The stored consent text is part of the governed surface and must pass the guard.
    text = consent_text(name="Sam")
    assert find_prohibited_words(text) == []
    # It is capacity-framed: it names authority + withdrawal + the minimum-visibility promise.
    assert "authority" in text.lower()
    assert "withdraw" in text.lower()


@pytest.mark.parametrize("word", EXPECTED_CLINICAL + EXPECTED_SURVEILLANCE_SUBSTRINGS)
def test_each_substring_word_is_actually_caught(word):
    # The guard is not vacuous: a string containing each substring word is rejected,
    # case-insensitively.
    assert find_prohibited_words(f"This mentions {word.upper()} explicitly.") == [word]
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"contains {word} here")


@pytest.mark.parametrize("word", EXPECTED_WORD_BOUNDED)
def test_each_word_bounded_label_is_caught_as_a_standalone_word(word):
    # The role / surveillance word is caught as a standalone word ...
    assert word in find_prohibited_words(f"You are the {word} of this.")
    with pytest.raises(ProhibitedCopyError):
        assert_clean(f"the {word} can do this")


def test_word_bounded_entries_do_not_false_trigger_inside_longer_words():
    # "case" must not fire inside "staircase"; "owner" not inside "downtowner"; "track" is a
    # SUBSTRING bar (it fires inside "tracking"), which is intended.
    assert find_prohibited_words("Meet them at the bottom of the staircase.") == []
    assert find_prohibited_words("A lowercase note about the showcase downtown.") == []
    # "subject" not inside "subjective"? subjective contains "subject" as a prefix but not a
    # whole word, so the word-boundary bar does not fire.
    assert find_prohibited_words("This is a subjective judgement.") == []


def test_clean_warm_copy_passes_the_guard():
    assert find_prohibited_words("Offer to help, and the family will confirm with you.") == []
    assert_clean("Thank you for offering", "Step back any time")  # must not raise


def test_ingress_rejection_copy_key_is_governed_and_clean():
    # Fix A: the INGRESS guard's user-facing 422 copy is itself governed and must pass the
    # Hub guard like every other emitted string. render() runs assert_clean internally, so a
    # prohibited word here would raise; it is also caught by the all-copy sweep above. It is
    # warm, capacity-framed, and names that the whole village can see the ask.
    text = render("need.content.rejected")
    assert find_prohibited_words(text) == []
    assert "village" in text.lower()
