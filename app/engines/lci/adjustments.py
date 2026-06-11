"""The LCI calc seam: the start value, the outcome-by-tier table, the bounds.

Product.md section 4.8 (AUTHORITATIVE) defines the index to the number; this module
is the single place those numbers live, isolated so a future owner change is a data
edit here, not a logic rewrite. Everything in app/engines/lci/index.py folds over
these constants and never re-states a number.

The exact spec (section 4.8, HardRules/Api/Modules/Index.md):
  - START at 50 on a chapter's first pulse; the score adjusts cumulatively and
    never resets.
  - Each pulse adjusts by f(outcome, the activity's recommended tier):

        Outcome    Full Engagement  Modified Participation  Continuity Pivot
        Well       +10              +7                      +5
        Okay       +3               +5                      +3
        Difficult  -8                0                      +2

    (The Pivot column was restored 2026-06-11 from the source PDF; the
    Difficult/Pivot cell is +2, POSITIVE, because the plan correctly protected the
    family. All twelve cells are pinned in tests/test_engine_lci.py.)
  - A SKIPPED pulse adjusts by 0 (it never harms the score).
  - Bounds 0 to 100; round to the nearest whole number after each change.

The tier vocabulary is the engine's Tier enum (Full/Modified/Pivot) so there is one
definition of the tier across the LCE and the LCI. The outcome vocabulary is the
Outcome enum (the app's "well"/"okay"/"difficult" wire codes plus "skipped").
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Dict, Tuple

from app.models.seed import Tier

# The starting score on a chapter's first pulse (section 4.8). Deliberately 50: one
# good day moves to 60, one hard day to 42, so no single day is a false alarm.
STARTING_SCORE = 50

# The 0 to 100 bounds the score is clamped to after every change (section 4.8).
MIN_SCORE = 0
MAX_SCORE = 100


class Outcome(str, Enum):
    """A pulse outcome (Product.md section 4.7 / 4.8).

    WELL/OKAY/DIFFICULT are the two-tap outcomes the Coordinator picks (the app's
    "well"/"okay"/"difficult" wire codes). SKIPPED is the recorded state after a
    Pulse is dismissed twice (section 4.7): it is a real recorded outcome with a 0
    adjustment, never a penalty.
    """

    WELL = "well"
    OKAY = "okay"
    DIFFICULT = "difficult"
    SKIPPED = "skipped"


# The section 4.8 outcome-by-tier adjustment table, keyed (Outcome, Tier) -> delta.
# This is the ONLY place the twelve cells live; the index folds over it. SKIPPED is
# handled separately (a flat 0 for any tier) so a skipped pulse with any stored tier
# never moves the score.
_ADJUSTMENTS: Dict[Tuple[Outcome, Tier], int] = {
    (Outcome.WELL, Tier.FULL): 10,
    (Outcome.WELL, Tier.MODIFIED): 7,
    (Outcome.WELL, Tier.PIVOT): 5,
    (Outcome.OKAY, Tier.FULL): 3,
    (Outcome.OKAY, Tier.MODIFIED): 5,
    (Outcome.OKAY, Tier.PIVOT): 3,
    (Outcome.DIFFICULT, Tier.FULL): -8,
    (Outcome.DIFFICULT, Tier.MODIFIED): 0,
    (Outcome.DIFFICULT, Tier.PIVOT): 2,
}

# A skipped pulse is a 0 adjustment regardless of tier (section 4.8).
_SKIPPED_ADJUSTMENT = 0


def adjustment_for(outcome: Outcome, tier: Tier) -> int:
    """The section 4.8 score delta for one pulse: f(outcome, recommended tier).

    A skipped pulse is 0 for any tier. Every Well/Okay/Difficult x Full/Modified/
    Pivot pair is in the table, so a lookup miss is a programming error (a new
    outcome or tier added without a cell), surfaced as a KeyError rather than a
    silent 0.
    """
    if outcome is Outcome.SKIPPED:
        return _SKIPPED_ADJUSTMENT
    return _ADJUSTMENTS[(outcome, tier)]


def apply_adjustment(current: float, delta: int) -> int:
    """Apply a delta to the current score, then round and clamp to 0..100.

    Round to the nearest whole number after the change (section 4.8), half-up via an
    exact Decimal so a .5 always rounds up and a float artefact cannot perturb it
    (the same rounding discipline as the LCE calc seam). The result is clamped into
    the 0 to 100 bounds. current may be a float (a stored score is whole, but the
    fold keeps it numeric); the return is always an int in 0..100.
    """
    raw = Decimal(str(current)) + Decimal(delta)
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return _clamp(rounded)


def _clamp(value: int) -> int:
    """Clamp an integer score into the section 4.8 bounds (0 to 100)."""
    if value < MIN_SCORE:
        return MIN_SCORE
    if value > MAX_SCORE:
        return MAX_SCORE
    return value
