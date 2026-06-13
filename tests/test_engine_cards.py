"""Tests for the Continuity Card assembler (Product.md section 4.6).

The builder (app/engines/cards/builder.py) is a PURE function of a stored
activity_record + the care recipient's name, so it gets straight, no-DB tests:
  - it assembles the SAFE helper-facing content (first name only, activity, tier in
    plain words, intro, top strategies capped at 5, an if-difficult line);
  - it shows the care recipient's FIRST name only, never the full name (the privacy
    rule);
  - it runs every emitted string through the SHARED non-clinical guard
    (app/engines/alerts/guard.py), so a prohibited clinical word, whether in the fixed
    copy or in a stored strategy, trips the guard and the card does not build.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines.alerts.guard import ProhibitedWordError
from app.engines.cards import (
    MAX_CARD_STRATEGIES,
    build_card_content,
    build_freshness_note,
    first_name_only,
    public_safe_content,
)


def _activity(**overrides):
    """A stored-activity_record-shaped dict (only the fields the builder reads)."""
    base = {
        "id": "act-1",
        "child_id": "child-1",
        "chapter": "school",
        "activity_name": "School gate drop-off",
        "tier": "Pivot",
        "strategies": [
            {"title": "Pre-agreed distress protocol with school", "detail": "Agree it in advance."},
            {"title": "Send the card to school ahead of time", "detail": "So staff know the plan."},
            {"title": "Build in extra time", "detail": "No rushing at the gate."},
            {"title": "Do not force, use the agreed plan", "detail": "Calm over completion."},
            {"title": "A calm hand-off", "detail": "Keep goodbyes short and warm."},
            {"title": "A sixth strategy", "detail": "Should be dropped by the cap."},
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# first_name_only: the privacy rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "full,expected",
    [
        ("Ade", "Ade"),
        ("Ade Bello", "Ade"),
        ("  Ade   Bello  ", "Ade"),
        ("Ade-Marie Bello", "Ade-Marie"),
    ],
)
def test_first_name_only_returns_just_the_first_token(full, expected):
    assert first_name_only(full) == expected


def test_first_name_only_falls_back_when_empty():
    # An empty/whitespace name still yields readable, non-identifying copy.
    assert first_name_only("") == "your child"
    assert first_name_only("   ") == "your child"


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def test_build_card_uses_first_name_only_never_the_full_name():
    content = build_card_content(_activity(), "Ade Bello")
    assert content.child_first_name == "Ade"
    # The surname must appear nowhere on the card (intro, if-difficult, any field).
    blob = content.model_dump_json()
    assert "Bello" not in blob


def test_build_card_assembles_the_expected_shape():
    content = build_card_content(_activity(), "Ade Bello")
    assert content.activity_name == "School gate drop-off"
    assert content.chapter == "school"
    assert content.tier == "Pivot"
    # Pivot is restated in plain, warm, helper-facing words.
    assert content.tier_label == "Keeping things calm and steady"
    # The intro and if-difficult lines are present, warm, and name the first name.
    assert "Ade" in content.intro
    assert "Ade" in content.if_difficult
    assert content.intro and content.if_difficult


def test_build_card_includes_a_standing_safety_boundary_naming_the_first_name():
    # M1 (medical re-screen): every card carries a health-and-safety boundary that defers
    # anything medical to the family, names the care recipient by first name only, and is a
    # standing line on every card (not tier-specific).
    content = build_card_content(_activity(), "Ade Bello")
    assert content.safety_note
    assert "Ade" in content.safety_note
    assert "Bello" not in content.safety_note
    assert "family" in content.safety_note.lower()
    # The same boundary regardless of tier (it is a fixed, always-shown line); both
    # resolve to the first name "Ade", so the copy is identical across tiers.
    full = build_card_content(_activity(tier="Full"), "Ade")
    assert full.safety_note == content.safety_note


def test_build_card_caps_strategies_and_preserves_rank_order():
    content = build_card_content(_activity(), "Ade")
    assert len(content.strategies) == MAX_CARD_STRATEGIES
    # The order is the stored (engine-ranked) order; the 6th is dropped.
    assert content.strategies[0].title == "Pre-agreed distress protocol with school"
    titles = [s.title for s in content.strategies]
    assert "A sixth strategy" not in titles


def test_build_card_handles_a_flat_strategy_phrase():
    # The seed sometimes stores title == detail (a flat phrase); both fields fill.
    act = _activity(strategies=[{"title": "Visual schedule", "detail": "Visual schedule"}])
    content = build_card_content(act, "Ade")
    assert content.strategies[0].title == "Visual schedule"
    assert content.strategies[0].detail == "Visual schedule"


def test_build_card_handles_no_strategies():
    # A plan with no strategies still builds a card (tier + basics), section 4.6.
    content = build_card_content(_activity(strategies=[]), "Ade")
    assert content.strategies == []
    assert content.tier_label == "Keeping things calm and steady"


@pytest.mark.parametrize(
    "tier,label",
    [
        ("Full", "Taking part fully"),
        ("Modified", "Taking part with a few adjustments"),
        ("Pivot", "Keeping things calm and steady"),
    ],
)
def test_build_card_plain_tier_labels(tier, label):
    content = build_card_content(_activity(tier=tier), "Ade")
    assert content.tier_label == label
    assert content.tier == tier


# ---------------------------------------------------------------------------
# the SHARED non-clinical guard trips on a prohibited word
# ---------------------------------------------------------------------------


def test_build_card_trips_the_guard_on_a_prohibited_word_in_a_strategy():
    # A stored strategy carrying a prohibited clinical word ("therapy") must trip the
    # shared guard so the card never ships clinical language onto a shared link.
    bad = _activity(
        strategies=[{"title": "Continue the therapy plan", "detail": "Continue the therapy plan"}]
    )
    with pytest.raises(ProhibitedWordError):
        build_card_content(bad, "Ade")


def test_build_card_trips_the_guard_on_a_prohibited_word_in_the_activity_name():
    bad = _activity(activity_name="Clinical review meeting")
    with pytest.raises(ProhibitedWordError):
        build_card_content(bad, "Ade")


def test_build_card_clean_copy_passes_the_guard():
    # The fixed copy (intro, tier label, if-difficult, safety, freshness) is itself
    # clean: a normal card builds without tripping the guard.
    content = build_card_content(_activity(), "Ade")
    assert content is not None


# ---------------------------------------------------------------------------
# the freshness note + the read-time staleness anchor (the staleness finding)
# ---------------------------------------------------------------------------


def test_build_card_includes_a_freshness_note_naming_the_prepared_date():
    # The clinical board's MANDATORY staleness finding: every card carries a governed
    # line naming the date it was prepared and asking for an up-to-date version if old.
    # The date is formatted readably with no leading zero and no en/em dashes.
    when = datetime(2026, 6, 5, 9, 30, tzinfo=timezone.utc)
    content = build_card_content(_activity(), "Ade", generated_at=when)
    assert content.freshness_note
    assert "5 June 2026" in content.freshness_note
    assert "-" not in content.freshness_note  # no en/em dashes (writing convention)
    # generated_at is carried back so the app can show the card's age.
    assert content.generated_at == when
    # A freshly built card is, by definition, not stale (is_stale is a read-time signal).
    assert content.is_stale is False


def test_build_card_freshness_note_passes_the_shared_guard():
    # The freshness line is governed copy and is run through the SHARED non-clinical guard
    # like every other card string; the standalone builder is guarded too.
    note = build_freshness_note(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert note  # clean copy returns; a prohibited word would raise ProhibitedWordError
    assert "1 January 2026" in note


def test_build_card_defaults_generated_at_when_not_given():
    # With no explicit generated_at the builder stamps "now", so the card always has a
    # freshness note and a generated_at (the create path always passes the real value).
    content = build_card_content(_activity(), "Ade")
    assert content.generated_at is not None
    assert content.freshness_note


# ---------------------------------------------------------------------------
# public_safe_content: the PUBLIC (unauthenticated) card strips the recipient's NAME
# ---------------------------------------------------------------------------


def test_public_safe_content_removes_the_name_everywhere():
    # The public token card must carry NO recipient name. Build a card with a real name,
    # then strip it: the name appears in no field, and the heading is the neutral label.
    full = build_card_content(_activity(), "Ade Bello")
    assert "Ade" in full.model_dump_json()  # the name IS there before stripping
    safe = public_safe_content(full)
    blob = safe.model_dump_json()
    assert "Ade" not in blob and "Bello" not in blob
    assert safe.child_first_name == "this child"
    # The four name-bearing fields become the neutral, pronoun copy; none names the child.
    assert "Ade" not in safe.intro
    assert "Ade" not in safe.if_difficult
    assert "Ade" not in safe.safety_note


def test_public_safe_content_leaves_the_non_name_fields_unchanged():
    full = build_card_content(_activity(), "Ade Bello")
    safe = public_safe_content(full)
    # Everything that never carried the name is preserved exactly.
    assert safe.activity_name == full.activity_name
    assert safe.chapter == full.chapter
    assert safe.tier == full.tier
    assert safe.tier_label == full.tier_label
    assert safe.strategies == full.strategies
    assert safe.freshness_note == full.freshness_note
    assert safe.generated_at == full.generated_at
    assert safe.is_stale == full.is_stale


@pytest.mark.parametrize(
    "tier,fragment",
    [
        ("Full", "usually comfortable with this"),
        ("Modified", "join in well with a little support"),
        ("Pivot", "a big ask for them"),
    ],
)
def test_public_safe_content_intro_matches_the_tier(tier, fragment):
    # The neutral intro is the de-named version of the SAME tier's intro (meaning preserved).
    full = build_card_content(_activity(tier=tier), "Ade Bello")
    safe = public_safe_content(full)
    assert fragment in safe.intro
    assert "Ade" not in safe.intro


def test_public_safe_content_copy_passes_the_shared_guard():
    # The neutral public copy is fixed governed copy: it must pass the shared non-clinical
    # guard (screened here in CI, never at request time), like every other card string. A
    # banned word would raise ProhibitedWordError; a clean pass returns without raising.
    from app.engines.alerts.guard import assert_clean

    safe = public_safe_content(build_card_content(_activity(), "Ade"))
    assert_clean(safe.child_first_name, safe.intro, safe.if_difficult, safe.safety_note)
