"""Table-driven tests for the Life Continuity Engine (Product.md section 4.4).

These pin the AUTHORITATIVE engine output to the exact section 4.4 numbers,
computed by hand from the seeded base scores + the SL multipliers + the tag
modifiers, with the round-after-multiplier and cap-at-5 behaviour the PRD fixes
(the calc seam, app/engines/lce/scoring.py; the Task 12 score-resolution
decision). The engine is deterministic and reads the seeded rows, so the same
inputs always produce the same scores, total, tier, ranked strategies, and
per-dimension explanations: no live Supabase is needed (these call run_engine
directly).

The cases (real seed scenarios + profiles), each asserting the full step-by-step
section 4.4 output:
  - LOW: a low scenario, SL-LOW, no tags: base unchanged (multiplier x1.0, no
    modifiers). Pins the no-op path and a Full tier.
  - MID: a mid scenario, SL-MED, several permanent tags: pins the multiplier round
    AND the +2-per-dimension tag cap (three SN- tags cap Sensory at +2).
  - HIGH: a high scenario, SL-HIGH, a permanent tag + a TG- today flag: pins the
    caps and that the total reaches 20 (Continuity Pivot).
  - TODAY-PAST-CAP: the sharp case: a dimension lifted by permanent tags to the +2
    cap (base 2 -> 4) is then pushed to 5 by a today flag, proving today flags add
    PAST the +2 permanent cap (capped only at 5). Steps 3 and 4 are separate.
  - ROUND: SL-HIGH on a {3,2,3,2} base pins the multiplier round (3 x1.4 -> 4,
    2 x1.4 -> 3).
  - CUSTOM: an unknown activity falls back to the chapter average (section 4.4
    step 1) and the plan flags it.
Plus the tier-band boundaries at 8/9 and 13/14.
"""

from __future__ import annotations

import pytest

from app.engines.lce import run_engine
from app.engines.lce.engine import EngineResult
from app.models.seed import Dimension, Tier


def _scores(result: EngineResult) -> dict:
    return {d.value: v for d, v in result.scores.items()}


# ---------------------------------------------------------------------------
# The pinned table: each row is a full section 4.4 worked example.
# (label, chapter, activity_code, SL, permanent_tags, today_flags,
#  expected_scores, expected_total, expected_tier)
# ---------------------------------------------------------------------------

ENGINE_CASES = [
    # LOW: travel car (base 2/2/1/1), SL-LOW x1.0, no tags -> unchanged, total 6 Full.
    (
        "low-sl-low-no-tags",
        "travel",
        "car-journey-short-familiar-route-under-1-hour",
        "SL-LOW",
        [],
        [],
        {"temporal": 2, "sensory": 2, "logistical": 1, "human": 1},
        6,
        Tier.FULL,
    ),
    # MID: school parent meeting (base 4/1/3/5), SL-MED x1.2 -> {5,1,4,5} (round:
    # 4x1.2=4.8->5, 3x1.2=3.6->4); + three SN- tags on Sensory cap at +2 -> sensory
    # 1+2=3; + CM-NONVERBAL +1 Human -> human 5+1 capped 5. Final {5,3,4,5} total 17.
    (
        "mid-sl-med-sn-cap-plus-cm",
        "school",
        "parent-school-meeting-conflict-or-crisis",
        "SL-MED",
        ["SN-NOISE", "SN-CROWD", "SN-LIGHT", "CM-NONVERBAL"],
        [],
        {"temporal": 5, "sensory": 3, "logistical": 4, "human": 5},
        17,
        Tier.PIVOT,
    ),
    # HIGH: travel airport anxious (base 5/5/5/4), SL-HIGH x1.4 -> all capped 5
    # ({5,5,5, 4x1.4=5.6->6 cap 5}); + TR-CHANGE +1 all (already 5); + TG-ILL +2 all
    # (already 5). Final {5,5,5,5} total 20 Pivot (the ceiling).
    (
        "high-sl-high-stacked-to-20",
        "travel",
        "airport-departure-child-highly-anxious-or-dysregulated",
        "SL-HIGH",
        ["TR-CHANGE"],
        ["TG-ILL"],
        {"temporal": 5, "sensory": 5, "logistical": 5, "human": 5},
        20,
        Tier.PIVOT,
    ),
    # TODAY-PAST-CAP: school morning routine (base 3/2/3/2), SL-LOW x1.0 -> unchanged;
    # permanent SN-NOISE+SN-CROWD on Sensory cap at +2 -> sensory 2+2=4; today
    # TG-FATIGUE +1 all -> {4,5,4,3} (sensory 4+1=5, PAST the +2 permanent cap,
    # capped at 5). Final total 16 Pivot. This is the separate-steps proof.
    (
        "today-flag-pushes-past-permanent-cap",
        "school",
        "morning-routine-standard-school-day",
        "SL-LOW",
        ["SN-NOISE", "SN-CROWD"],
        ["TG-FATIGUE"],
        {"temporal": 4, "sensory": 5, "logistical": 4, "human": 3},
        16,
        Tier.PIVOT,
    ),
    # ROUND: career morning routine (base 3/2/3/2), SL-HIGH x1.4, no tags. Pins the
    # multiplier round: 3x1.4=4.2->4, 2x1.4=2.8->3. Final {4,3,4,3} total 14 Pivot.
    (
        "round-after-sl-high-multiplier",
        "career",
        "morning-routine-standard-school-day",
        "SL-HIGH",
        [],
        [],
        {"temporal": 4, "sensory": 3, "logistical": 4, "human": 3},
        14,
        Tier.PIVOT,
    ),
]


@pytest.mark.parametrize(
    "label, chapter, activity_code, sl, permanent_tags, today_flags, "
    "expected_scores, expected_total, expected_tier",
    ENGINE_CASES,
    ids=[c[0] for c in ENGINE_CASES],
)
def test_engine_pins_section_4_4_numbers(
    label,
    chapter,
    activity_code,
    sl,
    permanent_tags,
    today_flags,
    expected_scores,
    expected_total,
    expected_tier,
):
    result = run_engine(
        chapter=chapter,
        activity_code=activity_code,
        support_level_code=sl,
        permanent_tags=permanent_tags,
        today_flags=today_flags,
    )
    assert _scores(result) == expected_scores, label
    assert result.total == expected_total, label
    assert result.tier == expected_tier, label
    # The total is always the sum of the four final cells (range 4 to 20).
    assert result.total == sum(result.scores.values())
    assert 4 <= result.total <= 20


def test_today_flag_adds_past_the_permanent_plus_two_cap():
    # The sharp behaviour, asserted on the dimension directly: Sensory base 2, the
    # two permanent SN- tags cap the tag contribution at +2 (-> 4), and the today
    # TG-FATIGUE flag adds one MORE (-> 5), past where the +2 permanent cap stopped.
    result = run_engine(
        chapter="school",
        activity_code="morning-routine-standard-school-day",
        support_level_code="SL-LOW",
        permanent_tags=["SN-NOISE", "SN-CROWD"],
        today_flags=["TG-FATIGUE"],
    )
    assert result.base_scores[Dimension.SENSORY] == 2
    assert result.scores[Dimension.SENSORY] == 5


def test_determinism_same_inputs_same_output():
    kwargs = dict(
        chapter="social",
        activity_code="birthday-party-large-or-unfamiliar-setting",
        support_level_code="SL-MED",
        permanent_tags=["SN-NOISE", "TR-CHANGE"],
        today_flags=["TG-ANXIETY"],
    )
    first = run_engine(**kwargs)
    second = run_engine(**kwargs)
    assert _scores(first) == _scores(second)
    assert first.total == second.total
    assert first.tier == second.tier
    assert [s.title for s in first.strategies] == [s.title for s in second.strategies]


# ---------------------------------------------------------------------------
# Tier-band boundaries (section 4.4 step 6): 4-8 Full, 9-13 Modified, 14-20 Pivot
# ---------------------------------------------------------------------------


def test_full_band_upper_boundary_total_8():
    # family bedtime (base 3/2/2/1), SL-LOW, no tags -> total 8, the top of Full.
    result = run_engine(
        chapter="family",
        activity_code="bedtime-routine-typical-evening",
        support_level_code="SL-LOW",
        permanent_tags=[],
        today_flags=[],
    )
    assert result.total == 8
    assert result.tier == Tier.FULL


def test_modified_band_lower_boundary_total_9():
    # Push the family-bedtime total 8 to 9 with a single +1 today flag on a dimension
    # below the cap (TG-HUNGER +1 Temporal: 3 -> 4), crossing into Modified.
    result = run_engine(
        chapter="family",
        activity_code="bedtime-routine-typical-evening",
        support_level_code="SL-LOW",
        permanent_tags=[],
        today_flags=["TG-HUNGER"],
    )
    assert result.total == 9
    assert result.tier == Tier.MODIFIED


def test_modified_band_upper_boundary_total_13():
    # school parent meeting (base 4/1/3/5), SL-LOW, no tags -> total 13, top of
    # Modified (this is the source's own tier for the scenario).
    result = run_engine(
        chapter="school",
        activity_code="parent-school-meeting-conflict-or-crisis",
        support_level_code="SL-LOW",
        permanent_tags=[],
        today_flags=[],
    )
    assert result.total == 13
    assert result.tier == Tier.MODIFIED


def test_pivot_band_lower_boundary_total_14():
    # Push the meeting total 13 to 14 with a single +1 on Sensory (base 1 -> 2 via
    # one SN- tag), crossing into Pivot.
    result = run_engine(
        chapter="school",
        activity_code="parent-school-meeting-conflict-or-crisis",
        support_level_code="SL-LOW",
        permanent_tags=["SN-NOISE"],
        today_flags=[],
    )
    assert result.total == 14
    assert result.tier == Tier.PIVOT


# ---------------------------------------------------------------------------
# Custom activity -> chapter-average fallback (section 4.4 step 1)
# ---------------------------------------------------------------------------


def test_custom_activity_uses_chapter_average_and_flags_it():
    # An unknown activity_code has no scenario row, so the engine uses the school
    # chapter average (3/3/3/3 = 12 Modified) and marks used_chapter_average.
    result = run_engine(
        chapter="school",
        activity_code="totally-custom-thing",
        support_level_code="SL-LOW",
        permanent_tags=[],
        today_flags=[],
    )
    assert result.used_chapter_average is True
    assert _scores(result) == {"temporal": 3, "sensory": 3, "logistical": 3, "human": 3}
    assert result.total == 12
    assert result.tier == Tier.MODIFIED
    # The per-dimension explanations tell the Coordinator the scores are an estimate.
    assert "estimate" in result.dimension_explanations["temporal"].lower()


def test_seeded_activity_does_not_flag_chapter_average():
    result = run_engine(
        chapter="family",
        activity_code="bedtime-routine-typical-evening",
        support_level_code="SL-LOW",
        permanent_tags=[],
        today_flags=[],
    )
    assert result.used_chapter_average is False


# ---------------------------------------------------------------------------
# Missing / unknown support level falls back to x1.0 (no uplift, never an error)
# ---------------------------------------------------------------------------


def test_missing_support_level_applies_no_multiplier():
    # A child with no support_level_code yet: the engine applies x1.0 (SL-LOW) so it
    # never fails on an incomplete profile (the base is unchanged by the multiplier).
    result = run_engine(
        chapter="travel",
        activity_code="car-journey-short-familiar-route-under-1-hour",
        support_level_code=None,
        permanent_tags=[],
        today_flags=[],
    )
    assert _scores(result) == {"temporal": 2, "sensory": 2, "logistical": 1, "human": 1}


# ---------------------------------------------------------------------------
# Strategies (section 4.4 step 7) + non-clinical explanations (step 10)
# ---------------------------------------------------------------------------


def test_strategies_are_returned_in_seed_order_for_a_seeded_scenario():
    # Step 7 starter order: the scenario's seeded strategies, ranked. (Promotion /
    # suppression / cross-context is the Task 9 hook; not exercised here.)
    result = run_engine(
        chapter="travel",
        activity_code="airport-departure-standard",
        support_level_code="SL-LOW",
        permanent_tags=[],
        today_flags=[],
    )
    assert len(result.strategies) >= 1
    # The first seeded airport-standard strategy is carried verbatim.
    assert result.strategies[0].body == (
        "Request hidden disability lanyard or airport assistance"
    )
    # No starter strategy carries a cross-context label (that is Task 9).
    assert all(s.cross_context_chapter is None for s in result.strategies)


def test_dimension_explanations_are_present_non_clinical_and_per_dimension():
    result = run_engine(
        chapter="social",
        activity_code="birthday-party-large-or-unfamiliar-setting",
        support_level_code="SL-MED",
        permanent_tags=["SN-NOISE"],
        today_flags=["TG-ANXIETY"],
    )
    # One sentence per dimension.
    assert set(result.dimension_explanations.keys()) == {
        "temporal",
        "sensory",
        "logistical",
        "human",
    }
    # Non-clinical: none of the prohibited clinical words appear (section 4.9).
    prohibited = [
        "symptom",
        "diagnos",
        "mental health",
        "depression",
        "anxiety disorder",
        "clinical",
        "treatment",
        "therapy",
    ]
    blob = " ".join(result.dimension_explanations.values()).lower()
    assert not [w for w in prohibited if w in blob], blob
    # Every sentence is non-empty.
    for sentence in result.dimension_explanations.values():
        assert sentence.strip()


# ---------------------------------------------------------------------------
# The calc seam (scoring.py): round-after-multiplier + cap-at-5
# ---------------------------------------------------------------------------


def test_calc_seam_rounds_half_up_on_an_exact_decimal():
    # The seam rounds an EXACT Decimal product half-up. A hypothetical 2.5 must round
    # to 3 (half-up), not 2 (banker's), and the cap holds at 5. This pins the mode
    # independently of the current multipliers (which never land on .5).
    from app.engines.lce.scoring import apply_multiplier_and_round, cap_dimension

    assert apply_multiplier_and_round(5, 0.5) == 3  # 2.5 -> 3 (half-up)
    assert apply_multiplier_and_round(4, 1.0) == 4
    assert cap_dimension(7) == 5
    assert cap_dimension(3) == 3
