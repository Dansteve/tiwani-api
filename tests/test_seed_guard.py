"""The non-clinical prohibited-words guard over the WHOLE seed (section 4.9).

TIWANI is non-clinical infrastructure: governed copy may only signpost COMMUNITY and
statutory support and must NEVER use the prohibited clinical vocabulary (root CLAUDE.md,
Product.md section 4.9). The shared guard (app/engines/alerts/guard.py) already runs at
render time over emitted Erosion Alert copy and over the Continuity Card, but it did NOT
run over the SEEDED Knowledge Base + Tag Architecture content. A future seed edit could
introduce a prohibited clinical word into a strategy, a scenario explanation, or a tag
description and nothing would catch it.

This test closes that gap. It loads the FULL seed through the real loader (load_seed)
and asserts the SAME guard (assert_clean / find_prohibited_words, no second word list)
passes over EVERY user-facing seeded string: every scenario's activity name, scoring
explanation (rationale), and ranked strategy title + body; and every tag modifier's
description (rationale). The strings are gathered GENERICALLY by walking each loaded row
and taking every str-typed field, so a new scenario, a new strategy, a new tag row, or a
new string field on any of those is covered automatically: a prohibited clinical word
anywhere in the seed fails this test.

The seed is CLEAN today (this test passes); the point is to keep it enforced. This test
does not change the seed content; it only guards it.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.engines.alerts.guard import (
    PROHIBITED_WORDS,
    ProhibitedWordError,
    assert_clean,
    find_prohibited_words,
)
from app.seed import load_seed


def _strings_of(obj) -> list[tuple[str, str]]:
    """Every (field_name, value) string field of one loaded seed row.

    Generic over the row shape: it reads the row's own attribute dict (the loaded
    rows are frozen pydantic models / dataclasses), so any new str field is picked up
    without editing this test. Enum fields (tier, dimension) are str subclasses and
    are included via their value, which is harmless: they carry fixed safe codes and
    the guard would still flag a prohibited substring in any of them.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        items = dataclasses.asdict(obj).items()
    elif hasattr(obj, "__dict__"):
        items = vars(obj).items()
    else:  # pragma: no cover - the loaded rows always expose one of the above
        return []
    out: list[tuple[str, str]] = []
    for name, value in items:
        if isinstance(value, str):
            out.append((name, value))
    return out


def _all_seed_strings() -> list[tuple[str, str]]:
    """Every governed string in the loaded seed, as (location, text) pairs.

    Walks the SeedTables the engine actually reads: each scenario (its own string
    fields plus each ranked strategy's title + body) and each tag modifier row. The
    location label names the surface so a failure points straight at the offending
    row. New rows are covered because this iterates the loaded collections; new string
    fields are covered because _strings_of takes every str field.
    """
    tables = load_seed()
    collected: list[tuple[str, str]] = []

    for scenario in tables.scenarios:
        where = f"scenario {scenario.chapter}/{scenario.activity_code}"
        for field, text in _strings_of(scenario):
            collected.append((f"{where}.{field}", text))
        for strategy in scenario.strategies:
            for field, text in _strings_of(strategy):
                collected.append((f"{where}.strategy[{strategy.rank}].{field}", text))

    for modifier in tables.tag_modifiers:
        where = f"tag {modifier.tag_code}/{modifier.dimension.value}"
        for field, text in _strings_of(modifier):
            collected.append((f"{where}.{field}", text))

    return collected


def test_no_seeded_string_contains_a_prohibited_word():
    # The whole seed surface: every scenario activity name + explanation + strategy
    # title/body, and every tag description. The same shared guard the alert and card
    # builders use (no second word list). A prohibited word anywhere fails here.
    offenders = {
        location: find_prohibited_words(text)
        for location, text in _all_seed_strings()
        if find_prohibited_words(text)
    }
    assert offenders == {}, (
        f"prohibited clinical words found in seeded content: {offenders}"
    )


def test_assert_clean_passes_over_the_whole_seed():
    # assert_clean is the render-time gate the engines call; prove it does not raise
    # over the full seed (the seed is clean today), exercising the guard exactly as
    # production code does rather than only the find_* helper.
    assert_clean(*[text for _, text in _all_seed_strings()])


def test_the_guarded_surfaces_are_actually_present():
    # Guard against a vacuous pass: confirm the collector really reaches each named
    # user-facing surface (activity name, scenario explanation, strategy title + body,
    # tag description), so a broken loader or empty seed would fail here instead of
    # silently passing the guard above.
    locations = {location for location, _ in _all_seed_strings()}
    assert any(loc.endswith(".activity_name") for loc in locations)
    assert any(loc.endswith(".rationale") and loc.startswith("scenario ") for loc in locations)
    assert any(".strategy[" in loc and loc.endswith(".title") for loc in locations)
    assert any(".strategy[" in loc and loc.endswith(".body") for loc in locations)
    assert any(loc.startswith("tag ") and loc.endswith(".rationale") for loc in locations)
    # The seed is substantial (74 scenarios, 44 tag rows), so the surface is large.
    assert len(locations) > 500


@pytest.mark.parametrize("word", PROHIBITED_WORDS)
def test_a_prohibited_word_injected_into_the_seed_would_be_caught(word):
    # The guard is not vacuous on the seed path: if any collected seed string DID carry
    # a prohibited word, assert_clean over the collected strings would raise. Simulate
    # one tainted seed string alongside the real (clean) ones and confirm it is caught.
    tainted = [text for _, text in _all_seed_strings()]
    tainted.append(f"Prepare a calm space and avoid {word} discussion.")
    with pytest.raises(ProhibitedWordError):
        assert_clean(*tainted)
