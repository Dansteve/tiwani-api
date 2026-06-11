"""The Erosion Alert engine (Product.md section 4.9, AUTHORITATIVE).

Deterministic, table-driven, PURE functions over ONE chapter's history. No DB, no
clock: the evaluation instant (`now`) is passed in, never read from the wall clock
here. This module is the only definition of the alert thresholds; the service
(app/services/alerts.py) fetches the stored activity_record / pulse_record /
lci_snapshot rows for a chapter and the chapter's current LCI, calls evaluate(), and
persists the result. The governed COPY lives in app/engines/alerts/copy.py, kept
separate from this numeric logic.

Alerts are triggered by the COMBINATION of recommended tier and pulse outcome over
time, never one alone, evaluated after every pulse, per chapter. A higher level
REPLACES any lower one, so evaluate() returns the single highest level whose
condition is met (or None).

The exact thresholds (section 4.9, transcribed; the numbers are the named constants
below):

  L1 Early signal:
    Modified OR Pivot recommended in >= 3 activities in the last 30 days
    AND Difficult/Okay outcomes in >= 3 pulses in the last 30 days.

  L2 Sustained pressure:
    the L1 thresholds reached at >= 5 in 30 days,
    OR the chapter LCI declining for 3 weekly snapshots in a row.

  L3 Critical erosion:
    Pivot recommended in >= 3 activities in the last 14 days
    AND Difficult in >= 3 pulses in the last 14 days,
    OR the chapter LCI below 30.

"Recommended tier" is the stored activity_record.tier_recommended; the pulse outcome
is the stored pulse_record.outcome_code; the LCI inputs are the chapter's current
section 4.8 score and its weekly snapshot history (app/engines/lci).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Optional, Sequence

from app.engines.lci import Outcome
from app.models.seed import Tier

# --- the section 4.9 windows + counts (the only place these numbers live) -----
WINDOW_30_DAYS = timedelta(days=30)
WINDOW_14_DAYS = timedelta(days=14)

# L1 / L2 use the 30-day window; the counts are >= 3 (L1) and >= 5 (L2).
L1_COUNT = 3
L2_COUNT = 5
# L3 uses the 14-day window; the count is >= 3.
L3_COUNT = 3

# The chapter LCI thresholds (section 4.9): L2 fires on a 3-weekly-snapshot decline;
# L3 fires when the chapter LCI is strictly below 30.
LCI_DECLINE_SNAPSHOTS = 3
LCI_CRITICAL_BELOW = 30

# The tiers that count as "pressure" for the activity thresholds. L1/L2 count Modified
# OR Pivot; L3 counts Pivot only. The pulse outcomes that count: L1/L2 count Difficult
# OR Okay; L3 counts Difficult only. (Well is never a pressure signal.)
_L1_L2_TIERS = (Tier.MODIFIED, Tier.PIVOT)
_L3_TIERS = (Tier.PIVOT,)
_L1_L2_OUTCOMES = (Outcome.DIFFICULT, Outcome.OKAY)
_L3_OUTCOMES = (Outcome.DIFFICULT,)


class AlertLevel(IntEnum):
    """The Erosion Alert level (section 4.9). Higher replaces lower.

    An IntEnum so the levels order naturally (L3 > L2 > L1) for the
    higher-replaces-lower and the dismissal "worsen past the next threshold" rules,
    and so the stored value is the plain 1/2/3 the dashboard's ChapterStatus.alert_level
    and the app expect.
    """

    L1 = 1
    L2 = 2
    L3 = 3


@dataclass(frozen=True)
class ActivityPoint:
    """One prepared activity in a chapter: its recommended tier and when it was prepared.

    tier is the STORED activity_record.tier_recommended (never re-derived). at is the
    activity's creation instant, used only to test the 30-day / 14-day windows.
    """

    tier: Tier
    at: datetime


@dataclass(frozen=True)
class PulseOutcomePoint:
    """One recorded pulse in a chapter: its outcome and when it was recorded.

    outcome is the stored pulse_record.outcome_code. at is the pulse instant, used
    only to test the windows. (A skipped pulse is never a pressure outcome, so it is
    simply not in the counted sets.)
    """

    outcome: Outcome
    at: datetime


@dataclass(frozen=True)
class ChapterHistory:
    """The minimal per-chapter inputs the alert engine evaluates (section 4.9).

    activities + pulses are the windowed counts' source; current_lci is the chapter's
    current section 4.8 score (None when the chapter has no pulse yet, in which case
    the LCI-based conditions cannot fire); weekly_snapshot_scores is the chapter's
    weekly LCI history OLDEST-FIRST (one score per week), used for the
    "declining for 3 weekly snapshots in a row" condition. The service builds this
    from the stored rows; the engine never touches the DB or the clock.
    """

    activities: Sequence[ActivityPoint] = field(default_factory=tuple)
    pulses: Sequence[PulseOutcomePoint] = field(default_factory=tuple)
    current_lci: Optional[int] = None
    weekly_snapshot_scores: Sequence[int] = field(default_factory=tuple)


def evaluate(history: ChapterHistory, *, now: datetime) -> Optional[AlertLevel]:
    """The active alert level for a chapter, or None. Higher replaces lower.

    Tests L3, then L2, then L1, and returns the FIRST (highest) whose section 4.9
    condition is met, so a chapter that meets L3 reports L3 even though it also meets
    L1 (the higher-replaces-lower rule). Pure: every window is measured against the
    passed-in `now`; no clock or DB is read here.
    """
    if _meets_l3(history, now=now):
        return AlertLevel.L3
    if _meets_l2(history, now=now):
        return AlertLevel.L2
    if _meets_l1(history, now=now):
        return AlertLevel.L1
    return None


# ---------------------------------------------------------------------------
# the per-level conditions (section 4.9, exactly)
# ---------------------------------------------------------------------------


def _meets_l1(history: ChapterHistory, *, now: datetime) -> bool:
    """L1: Modified/Pivot in >= 3 activities (30d) AND Difficult/Okay in >= 3 pulses (30d)."""
    pressure_activities = _count_activities(history.activities, _L1_L2_TIERS, WINDOW_30_DAYS, now)
    pressure_pulses = _count_pulses(history.pulses, _L1_L2_OUTCOMES, WINDOW_30_DAYS, now)
    return pressure_activities >= L1_COUNT and pressure_pulses >= L1_COUNT


def _meets_l2(history: ChapterHistory, *, now: datetime) -> bool:
    """L2: the L1 thresholds at >= 5 in 30 days, OR the chapter LCI declining 3 weekly snapshots.

    The two branches are an OR (section 4.9): either the same Modified/Pivot-and-
    Difficult/Okay counts both reach 5 in the 30-day window, or the chapter LCI has
    declined across 3 consecutive weekly snapshots.
    """
    pressure_activities = _count_activities(history.activities, _L1_L2_TIERS, WINDOW_30_DAYS, now)
    pressure_pulses = _count_pulses(history.pulses, _L1_L2_OUTCOMES, WINDOW_30_DAYS, now)
    counts_branch = pressure_activities >= L2_COUNT and pressure_pulses >= L2_COUNT
    return counts_branch or _lci_declining(history.weekly_snapshot_scores)


def _meets_l3(history: ChapterHistory, *, now: datetime) -> bool:
    """L3: Pivot in >= 3 activities (14d) AND Difficult in >= 3 pulses (14d), OR LCI < 30.

    The two branches are an OR (section 4.9): either Pivot was recommended in >= 3
    activities and Difficult was recorded in >= 3 pulses, both within 14 days, or the
    chapter LCI is strictly below 30.
    """
    pivot_activities = _count_activities(history.activities, _L3_TIERS, WINDOW_14_DAYS, now)
    difficult_pulses = _count_pulses(history.pulses, _L3_OUTCOMES, WINDOW_14_DAYS, now)
    counts_branch = pivot_activities >= L3_COUNT and difficult_pulses >= L3_COUNT
    return counts_branch or _lci_critical(history.current_lci)


# ---------------------------------------------------------------------------
# the counting + LCI helpers
# ---------------------------------------------------------------------------


def _count_activities(
    activities: Sequence[ActivityPoint],
    tiers: Sequence[Tier],
    window: timedelta,
    now: datetime,
) -> int:
    """How many activities with a tier in `tiers` fall inside the rolling window.

    The window is rolling from `now`: an activity counts when its `at` is strictly
    after (now - window). (Strictly-after keeps a point exactly `window` old just
    outside, the natural reading of "in the last N days".)
    """
    cutoff = now - window
    return sum(1 for a in activities if a.tier in tiers and a.at > cutoff)


def _count_pulses(
    pulses: Sequence[PulseOutcomePoint],
    outcomes: Sequence[Outcome],
    window: timedelta,
    now: datetime,
) -> int:
    """How many pulses with an outcome in `outcomes` fall inside the rolling window."""
    cutoff = now - window
    return sum(1 for p in pulses if p.outcome in outcomes and p.at > cutoff)


def _lci_critical(current_lci: Optional[int]) -> bool:
    """True when the chapter LCI is strictly below 30 (section 4.9 L3 branch).

    None (no pulse yet, so no score) is NOT critical: a chapter with no LCI cannot be
    "below 30".
    """
    return current_lci is not None and current_lci < LCI_CRITICAL_BELOW


def _lci_declining(weekly_scores: Sequence[int]) -> bool:
    """True when the chapter LCI declined across 3 weekly snapshots in a row.

    `weekly_scores` is the chapter's weekly LCI history OLDEST-FIRST (one score per
    week). "Declining for 3 weekly snapshots in a row" needs three successive
    week-over-week DROPS, i.e. four consecutive weekly points each strictly less than
    the one before (s0 > s1 > s2 > s3). Fewer than four weekly points cannot show
    three drops, so it is not yet declining. Only the most recent run matters, so the
    last four points are tested.
    """
    needed = LCI_DECLINE_SNAPSHOTS + 1  # four points give three drops
    if len(weekly_scores) < needed:
        return False
    recent = list(weekly_scores[-needed:])
    return all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))
