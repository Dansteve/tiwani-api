"""Table-driven tests pinning the Life Continuity Index to Product.md section 4.8.

Section 4.8 is AUTHORITATIVE and owner-governed; these tests pin the index to the
number so a change cannot drift silently. They exercise the PURE engine
(app/engines/lci) directly, with no DB and no clock (the "as of" instant is passed
in). Pinned here:
  - all twelve outcome-by-tier adjustment cells + the skipped-is-0 rule;
  - start at 50 on a chapter's first pulse, cumulative never reset;
  - the mandate's worked sequences (Well/Modified -> 57; 50 -> 42 -> 52 -> 57);
  - Difficult under a Pivot recommendation is POSITIVE (+2);
  - the 0 and 100 bounds with rounding;
  - the overall average over chapters WITH a pulse only (no-data excluded), weighted
    equally, half-up rounded;
  - each trajectory band at the +3 / +/-2 / -3 / insufficient boundaries;
  - the sparse-data labels (< 3 pulses building your picture; none "--").
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines.lci import (
    Outcome,
    PulsePoint,
    Snapshot,
    Trajectory,
    adjustment_for,
    apply_adjustment,
    chapter_score,
    label_for,
    overall_score,
    prior_instant,
    snapshot_score_as_of,
    trajectory,
)
from app.models.seed import Tier


def _pulse(outcome: Outcome, tier: Tier, day: int = 1) -> PulsePoint:
    """A PulsePoint on the given June 2026 day (the fold orders by timestamp)."""
    at = datetime(2026, 6, day, 9, 0, tzinfo=timezone.utc)
    return PulsePoint(outcome=outcome, tier=tier, at=at)


# ---------------------------------------------------------------------------
# The twelve outcome-by-tier adjustment cells (section 4.8) + skipped
# ---------------------------------------------------------------------------

# (outcome, tier) -> the exact section 4.8 delta. All twelve cells, pinned.
ADJUSTMENT_CELLS = [
    (Outcome.WELL, Tier.FULL, 10),
    (Outcome.WELL, Tier.MODIFIED, 7),
    (Outcome.WELL, Tier.PIVOT, 5),
    (Outcome.OKAY, Tier.FULL, 3),
    (Outcome.OKAY, Tier.MODIFIED, 5),
    (Outcome.OKAY, Tier.PIVOT, 3),
    (Outcome.DIFFICULT, Tier.FULL, -8),
    (Outcome.DIFFICULT, Tier.MODIFIED, 0),
    (Outcome.DIFFICULT, Tier.PIVOT, 2),
]


@pytest.mark.parametrize("outcome,tier,expected", ADJUSTMENT_CELLS)
def test_adjustment_table_every_cell(outcome, tier, expected):
    assert adjustment_for(outcome, tier) == expected


@pytest.mark.parametrize("tier", [Tier.FULL, Tier.MODIFIED, Tier.PIVOT])
def test_skipped_pulse_is_zero_for_every_tier(tier):
    # A skipped pulse never moves the score, whatever the stored tier (section 4.8).
    assert adjustment_for(Outcome.SKIPPED, tier) == 0


def test_difficult_under_pivot_is_positive():
    # The plan correctly protected the family, so a hard day under a Pivot
    # recommendation scores POSITIVELY (+2), not negatively (section 4.8 note).
    assert adjustment_for(Outcome.DIFFICULT, Tier.PIVOT) == 2
    assert chapter_score([_pulse(Outcome.DIFFICULT, Tier.PIVOT)]) == 52


# ---------------------------------------------------------------------------
# Start at 50 + cumulative fold (section 4.8 worked sequences)
# ---------------------------------------------------------------------------


def test_first_pulse_starts_at_50_then_adjusts():
    # A fresh chapter's first pulse: Well on a Modified activity -> 50 + 7 = 57.
    assert chapter_score([_pulse(Outcome.WELL, Tier.MODIFIED)]) == 57


def test_cumulative_sequence_never_resets():
    # 50 -> Difficult/Full (-8) = 42 -> Well/Full (+10) = 52 -> Okay/Modified (+5) = 57.
    seq = [
        _pulse(Outcome.DIFFICULT, Tier.FULL, 1),
        _pulse(Outcome.WELL, Tier.FULL, 2),
        _pulse(Outcome.OKAY, Tier.MODIFIED, 3),
    ]
    assert chapter_score(seq) == 57


def test_fold_is_independent_of_input_order():
    # The fold sorts by timestamp, so a shuffled fetch order gives the same score.
    ordered = [
        _pulse(Outcome.DIFFICULT, Tier.FULL, 1),
        _pulse(Outcome.WELL, Tier.FULL, 2),
        _pulse(Outcome.OKAY, Tier.MODIFIED, 3),
    ]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    assert chapter_score(shuffled) == chapter_score(ordered) == 57


def test_a_skipped_pulse_moves_the_score_by_zero():
    # Inserting a skipped pulse between two real ones leaves the score unchanged.
    without_skip = [_pulse(Outcome.WELL, Tier.FULL, 1), _pulse(Outcome.OKAY, Tier.FULL, 3)]
    with_skip = [
        _pulse(Outcome.WELL, Tier.FULL, 1),
        _pulse(Outcome.SKIPPED, Tier.PIVOT, 2),
        _pulse(Outcome.OKAY, Tier.FULL, 3),
    ]
    assert chapter_score(with_skip) == chapter_score(without_skip) == 63


def test_no_pulse_chapter_is_none_not_zero():
    # A chapter with no pulse is excluded (None), never 0 (section 4.8).
    assert chapter_score([]) is None


# ---------------------------------------------------------------------------
# Bounds 0 to 100 with rounding (section 4.8)
# ---------------------------------------------------------------------------


def test_score_clamps_at_zero():
    # 9 x Difficult/Full = -72 from 50 -> below 0 -> clamped to 0.
    pulses = [_pulse(Outcome.DIFFICULT, Tier.FULL, d) for d in range(1, 10)]
    assert chapter_score(pulses) == 0


def test_score_clamps_at_one_hundred():
    # 10 x Well/Full = +100 from 50 -> above 100 -> clamped to 100.
    pulses = [_pulse(Outcome.WELL, Tier.FULL, d) for d in range(1, 11)]
    assert chapter_score(pulses) == 100


@pytest.mark.parametrize(
    "current,delta,expected",
    [
        (50, 10, 60),
        (0, -8, 0),  # already at floor, stays clamped
        (100, 10, 100),  # already at ceiling, stays clamped
        (3, -8, 0),  # crosses the floor
        (98, 5, 100),  # crosses the ceiling
    ],
)
def test_apply_adjustment_clamps(current, delta, expected):
    assert apply_adjustment(current, delta) == expected


# ---------------------------------------------------------------------------
# Overall average over chapters WITH a pulse only (section 4.8)
# ---------------------------------------------------------------------------


def test_overall_excludes_no_data_chapters():
    # Two chapters with data (57, 42) and one with none: the no-data chapter does NOT
    # drag the overall down. mean(57, 42) = 49.5 -> round half up -> 50.
    assert overall_score([57, 42, None]) == 50


def test_overall_weights_chapters_equally():
    # Equal weight: mean(60, 40, 80) = 60, regardless of how many pulses each had.
    assert overall_score([60, 40, 80]) == 60


def test_overall_is_none_when_no_chapter_has_data():
    assert overall_score([None, None, None]) is None
    assert overall_score([]) is None


def test_overall_rounds_half_up():
    # mean(50, 51) = 50.5 -> half up -> 51.
    assert overall_score([50, 51]) == 51


# ---------------------------------------------------------------------------
# Trajectory bands vs the 7-days-prior score (section 4.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,prior,expected",
    [
        (57, 54, Trajectory.STRENGTHENING),  # +3 -> strengthening (boundary)
        (60, 54, Trajectory.STRENGTHENING),  # +6 -> strengthening
        (56, 54, Trajectory.HOLDING_STEADY),  # +2 -> holding (upper boundary)
        (54, 54, Trajectory.HOLDING_STEADY),  # 0 -> holding
        (52, 54, Trajectory.HOLDING_STEADY),  # -2 -> holding (lower boundary)
        (51, 54, Trajectory.UNDER_PRESSURE),  # -3 -> under pressure (boundary)
        (40, 54, Trajectory.UNDER_PRESSURE),  # -14 -> under pressure
    ],
)
def test_trajectory_bands(current, prior, expected):
    assert trajectory(current, prior) == expected


@pytest.mark.parametrize("current,prior", [(57, None), (None, 54), (None, None)])
def test_trajectory_is_building_picture_without_two_points(current, prior):
    # No current score, or no 7-days-prior point, reads as "building your picture".
    assert trajectory(current, prior) == Trajectory.BUILDING_PICTURE


# ---------------------------------------------------------------------------
# Sparse-data labels (section 4.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pulse_count,expected",
    [
        (0, "--"),
        (1, "building your picture"),
        (2, "building your picture"),
        (3, None),
        (10, None),
    ],
)
def test_sparse_data_labels(pulse_count, expected):
    assert label_for(pulse_count) == expected


# ---------------------------------------------------------------------------
# Snapshot look-back (the trajectory's 7-days-prior source)
# ---------------------------------------------------------------------------


def test_snapshot_score_as_of_picks_latest_at_or_before():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)
    look_back = prior_instant(now)  # 2026-06-13
    snaps = [
        Snapshot(54, datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)),
        Snapshot(56, datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc)),
        Snapshot(60, datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc)),  # after look_back, ignored
    ]
    # The latest snapshot at or before 2026-06-13 is the 2026-06-12 one (56).
    assert snapshot_score_as_of(snaps, look_back) == 56


def test_snapshot_score_as_of_is_none_when_no_old_enough_snapshot():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)
    look_back = prior_instant(now)
    snaps = [Snapshot(60, datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc))]
    assert snapshot_score_as_of(snaps, look_back) is None
