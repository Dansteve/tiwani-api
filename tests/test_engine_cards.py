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

import pytest

from app.engines.alerts.guard import ProhibitedWordError
from app.engines.cards import MAX_CARD_STRATEGIES, build_card_content, first_name_only


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
    # The fixed copy (intro, tier label, if-difficult) is itself clean: a normal card
    # builds without tripping the guard.
    content = build_card_content(_activity(), "Ade")
    assert content is not None
