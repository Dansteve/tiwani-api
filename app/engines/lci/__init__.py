"""LCI: the Life Continuity Index (Product.md section 4.8, AUTHORITATIVE).

A 0 to 100 resilience score, per Life Chapter and overall, computed server-side
from stored Pulse outcomes and the stored recommended tier, never from free text
and never recomputed in the app. This package is the ONLY definition of the index.

Module file: HardRules/Api/Modules/Index.md. Read Product.md section 4.8 (the
authoritative source) alongside it before changing anything here.

Layout:
  adjustments.py   the calc seam: STARTING_SCORE 50, the twelve-cell outcome-by-tier
                   table, the skipped-is-0 rule, the 0 to 100 bounds + half-up
                   rounding. The only place the section 4.8 numbers live.
  index.py         pure, table-driven functions over a chapter's pulse history:
                   chapter_score (start 50, fold each pulse), chapter_score_as_of
                   (a past score from the live history), overall_score (equal-
                   weighted mean of chapters WITH a pulse), trajectory (the weekly
                   +3 / +/-2 / -3 / insufficient bands), label_for (the sparse
                   "building your picture" / "--" labels), and the snapshot helpers
                   the weekly trajectory reads.

The persistence and clock live in app/services/lci.py (it fetches the stored
pulse_record + lci_snapshot rows and supplies `now`); this package stays pure.
"""

from app.engines.lci.adjustments import (
    MAX_SCORE,
    MIN_SCORE,
    STARTING_SCORE,
    Outcome,
    adjustment_for,
    apply_adjustment,
)
from app.engines.lci.index import (
    BUILDING_PICTURE_LABEL,
    NO_DATA_LABEL,
    SPARSE_PULSE_THRESHOLD,
    PulsePoint,
    Snapshot,
    Trajectory,
    chapter_score,
    chapter_score_as_of,
    is_sparse,
    label_for,
    overall_score,
    prior_instant,
    snapshot_score_as_of,
    trajectory,
)

__all__ = [
    "MAX_SCORE",
    "MIN_SCORE",
    "STARTING_SCORE",
    "Outcome",
    "adjustment_for",
    "apply_adjustment",
    "BUILDING_PICTURE_LABEL",
    "NO_DATA_LABEL",
    "SPARSE_PULSE_THRESHOLD",
    "PulsePoint",
    "Snapshot",
    "Trajectory",
    "chapter_score",
    "chapter_score_as_of",
    "is_sparse",
    "label_for",
    "overall_score",
    "prior_instant",
    "snapshot_score_as_of",
    "trajectory",
]
