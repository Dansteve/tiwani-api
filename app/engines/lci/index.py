"""The Life Continuity Index core (Product.md section 4.8, AUTHORITATIVE).

Deterministic, table-driven, PURE functions over a chapter's pulse history. No DB,
no clock: the "as of" instant for the weekly trajectory is passed in, never read
from the wall clock here. This module is the only definition of the index; the
service (app/services/lci.py) fetches the stored pulses and snapshots and calls
these functions, and the app renders the result and recomputes nothing.

A "pulse" here is the minimal triple the index needs: its outcome, the activity's
stored recommended tier, and its timestamp. Free text never enters the index
(structured codes only, the HardRules/Api/SETUP.md rule).

The exact formula (section 4.8, all numbers in app/engines/lci/adjustments.py):
  - a chapter score starts at 50 on its first pulse and folds the outcome-by-tier
    delta for each subsequent pulse, in time order, clamped 0 to 100 and rounded
    after each change; it never resets.
  - the OVERALL score is the equal-weighted mean of the chapter scores that have at
    least one pulse (chapters with no pulse are EXCLUDED, not zero), rounded.
  - the TRAJECTORY (recalculated weekly) compares the current chapter/overall score
    to its value 7 days prior: +3 or more Strengthening, within +/-2 Holding steady,
    -3 or more Under pressure, not enough data Building your picture.
  - SPARSE data: a chapter with fewer than 3 pulses shows its score with a "building
    your picture" label; a chapter with no pulse shows "--" (the api returns
    score=null).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Iterable, List, Optional, Sequence

from app.engines.lci.adjustments import (
    STARTING_SCORE,
    Outcome,
    adjustment_for,
    apply_adjustment,
)
from app.models.seed import Tier

# A chapter with fewer than this many pulses is "sparse" and shows the building-
# picture label alongside its score (section 4.8). At or above it, the score stands
# on its own. A chapter with zero pulses has no score at all (rendered "--").
SPARSE_PULSE_THRESHOLD = 3

# The trajectory look-back window and the band edges (section 4.8). The current
# score is compared to the score this many days earlier; a rise of at least
# STRENGTHENING_DELTA is Strengthening, a fall of at least UNDER_PRESSURE_DELTA is
# Under pressure, and anything in between (within +/-2) is Holding steady.
TRAJECTORY_LOOKBACK_DAYS = 7
STRENGTHENING_DELTA = 3
UNDER_PRESSURE_DELTA = -3

# The sparse-data labels (section 4.8). BUILDING_PICTURE_LABEL is shown for a
# chapter with 1 or 2 pulses (the score is real but still forming); NO_DATA_LABEL
# is the "--" a chapter with no pulse shows (its score is null on the wire).
BUILDING_PICTURE_LABEL = "building your picture"
NO_DATA_LABEL = "--"


class Trajectory(str, Enum):
    """The section 4.8 trajectory band, as the app's Trajectory union codes.

    The values match tiwani-app's `Trajectory` type (strengthening / holding_steady
    / under_pressure / building_picture) so the wire contract needs no remapping.
    BUILDING_PICTURE is the "not enough data" band (no 7-day-prior point to compare
    against yet).
    """

    STRENGTHENING = "strengthening"
    HOLDING_STEADY = "holding_steady"
    UNDER_PRESSURE = "under_pressure"
    BUILDING_PICTURE = "building_picture"


@dataclass(frozen=True)
class PulsePoint:
    """The minimal pulse data the index folds: outcome, stored tier, timestamp.

    outcome is the recorded outcome (WELL/OKAY/DIFFICULT/SKIPPED). tier is the
    activity's STORED recommended tier (never re-derived here, the Pulse hard rule).
    at is the pulse timestamp, used only to order the fold and to answer the
    7-days-prior trajectory question.
    """

    outcome: Outcome
    tier: Tier
    at: datetime


@dataclass(frozen=True)
class Snapshot:
    """One stored chapter LCI snapshot: the chapter's score at a past instant.

    Used for the weekly trajectory: the index compares the current score to the
    score from the latest snapshot at or before (now - 7 days). taken_at is the
    instant the snapshot recorded; score is the whole-number chapter score then.
    """

    score: int
    taken_at: datetime


def chapter_score(pulses: Iterable[PulsePoint]) -> Optional[int]:
    """The current chapter LCI: start at 50, fold every pulse in time order.

    Returns None when the chapter has no pulse (it is EXCLUDED from the overall
    average and rendered "--"), never 0. With at least one pulse the score starts at
    50 and applies each pulse's outcome-by-tier delta (a skipped pulse adds 0),
    clamped 0 to 100 and rounded after each step. The fold is over the pulses sorted
    by timestamp so the order is deterministic regardless of fetch order.
    """
    ordered = _in_time_order(pulses)
    if not ordered:
        return None
    score: int = STARTING_SCORE
    for pulse in ordered:
        score = apply_adjustment(score, _delta(pulse))
    return score


def chapter_score_as_of(pulses: Iterable[PulsePoint], as_of: datetime) -> Optional[int]:
    """The chapter score using only pulses at or before `as_of` (no clock read).

    The same fold as chapter_score, restricted to pulses whose timestamp is <=
    as_of. Returns None if no pulse had occurred by then (so there is no prior point
    to compare against, which reads as Building your picture). Used to reconstruct a
    past score from the live pulse history when a stored snapshot is not used.
    """
    eligible = [p for p in pulses if p.at <= as_of]
    return chapter_score(eligible)


def overall_score(chapter_scores: Iterable[Optional[int]]) -> Optional[int]:
    """The overall LCI: the equal-weighted mean of chapters that have a score.

    Chapters with no pulse (a None score) are EXCLUDED, not counted as zero (section
    4.8: they must not drag the score down). All chapters with at least one pulse are
    weighted equally. Returns the mean rounded to the nearest whole number, or None
    when no chapter has any pulse yet (the overall is "--").
    """
    present = [s for s in chapter_scores if s is not None]
    if not present:
        return None
    return _round_half_up(sum(present) / len(present))


def trajectory(current: Optional[int], prior: Optional[int]) -> Trajectory:
    """The section 4.8 trajectory band from the current score vs the 7-days-prior one.

    Building your picture when either point is missing (no score yet, or no
    7-days-prior point to compare against). Otherwise: a rise of +3 or more is
    Strengthening, a fall of -3 or more is Under pressure, and a change within +/-2
    is Holding steady. The caller supplies `prior` from the stored snapshot history
    (the live recompute uses chapter_score_as_of); this function only bands the
    delta.
    """
    if current is None or prior is None:
        return Trajectory.BUILDING_PICTURE
    delta = current - prior
    if delta >= STRENGTHENING_DELTA:
        return Trajectory.STRENGTHENING
    if delta <= UNDER_PRESSURE_DELTA:
        return Trajectory.UNDER_PRESSURE
    return Trajectory.HOLDING_STEADY


def label_for(pulse_count: int) -> Optional[str]:
    """The sparse-data label for a chapter with `pulse_count` pulses (section 4.8).

    No pulses -> the "--" no-data label. 1 or 2 pulses -> the "building your picture"
    label (the score is shown with it). 3 or more pulses -> no label (None): the
    score stands alone.
    """
    if pulse_count <= 0:
        return NO_DATA_LABEL
    if pulse_count < SPARSE_PULSE_THRESHOLD:
        return BUILDING_PICTURE_LABEL
    return None


def is_sparse(pulse_count: int) -> bool:
    """True when a chapter has data but fewer than 3 pulses (the building-picture state)."""
    return 0 < pulse_count < SPARSE_PULSE_THRESHOLD


def snapshot_score_as_of(
    snapshots: Sequence[Snapshot], as_of: datetime
) -> Optional[int]:
    """The chapter score from the latest stored snapshot at or before `as_of`.

    The section 4.8 trajectory compares to "the score 7 days prior". This picks the
    most recent snapshot whose taken_at is <= as_of (typically now - 7 days), so the
    comparison uses the recorded weekly history. Returns None when no snapshot is
    that old yet (the chapter is still building its picture).
    """
    eligible = [s for s in snapshots if s.taken_at <= as_of]
    if not eligible:
        return None
    latest = max(eligible, key=lambda s: s.taken_at)
    return latest.score


def prior_instant(now: datetime) -> datetime:
    """The instant the trajectory looks back to: now minus the 7-day window."""
    return now - timedelta(days=TRAJECTORY_LOOKBACK_DAYS)


def _delta(pulse: PulsePoint) -> int:
    """The section 4.8 adjustment for one pulse (skipped is 0, via the seam)."""
    return adjustment_for(pulse.outcome, pulse.tier)


def _in_time_order(pulses: Iterable[PulsePoint]) -> List[PulsePoint]:
    """The pulses sorted ascending by timestamp (the deterministic fold order)."""
    return sorted(pulses, key=lambda p: p.at)


def _round_half_up(value: float) -> int:
    """Round a mean to the nearest whole number, half-up (section 4.8 rounding)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
