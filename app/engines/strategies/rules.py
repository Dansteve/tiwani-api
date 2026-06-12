"""Strategy Library: the PURE section 4.10 rules (promotion, suppression, cross-context).

The learning layer's decision functions as deterministic functions of a saved item's counts
+ dimension tags. No DB, no clock, no randomness here (the same way app/engines/alerts/
evaluation.py is pure), so the thresholds are exhaustively table-testable. The data layer
(app/services/strategies.py) reads/writes the strategy_library_item rows; this module decides,
from a row's numbers, whether it is promoted, suppressed, or a cross-context match. Module
file: HardRules/Api/Modules/Strategies.md. Its ranking output is consumed by the LCE (Engine.md
step 7), but it NEVER changes a score, total, tier, or the LCI.

The exact rules (Product.md section 4.10, AUTHORITATIVE), built to the number:
  - PROMOTION (appears first next time): positive outcomes >= 2 AND more positives than
    negatives, specific to that recipient and scenario.
  - SUPPRESSION (excluded next time): removed 3 times for the same strategy + scenario;
    scenario-specific and REVERSIBLE (re-allow clears it).
  - OUTCOME ATTRIBUTION (MVP): a Pulse outcome applies EQUALLY to every strategy in that plan
    (a deliberate MVP simplification, Q8; do NOT "fix" without the PRODUCT OWNER).
  - CROSS-CONTEXT surfacing: a strategy with positive outcomes >= 2 is offered in OTHER chapters
    when it matches a high-scoring dimension (>= 3), labelled "Also worked in [chapter]",
    dismissible per chapter.

The numeric thresholds are NAMED here (never inlined at the call sites), the one place the
section 4.10 numbers live for the api so a rule change is a single edit.
"""

from __future__ import annotations

from typing import Iterable, Sequence

# Section 4.10 thresholds, exact. A strategy is PROMOTED at this many positive outcomes
# (and only if positives strictly exceed negatives). The same >= 2 positives gate qualifies a
# strategy for CROSS-CONTEXT surfacing.
PROMOTION_MIN_POSITIVES = 2
CROSS_CONTEXT_MIN_POSITIVES = 2

# Section 4.10: a strategy removed this many times for the same scenario is SUPPRESSED
# (excluded next time). Scenario-specific and reversible.
SUPPRESSION_REMOVAL_THRESHOLD = 3


def is_promoted(positive_count: int, negative_count: int) -> bool:
    """True when a strategy should be ranked first next time (section 4.10 promotion).

    The exact rule: positive outcomes >= 2 AND more positives than negatives. Both conditions
    are required, so a strategy with 2 positives and 2 negatives is NOT promoted (it has not
    net-helped), and a strategy with 1 positive and 0 negatives is NOT promoted (it has not
    cleared the >= 2 bar). Specific to one recipient + scenario (the caller passes that
    recipient's scenario-scoped counts).
    """
    return positive_count >= PROMOTION_MIN_POSITIVES and positive_count > negative_count


def crosses_suppression_threshold(removal_count: int) -> bool:
    """True when this many removals reaches the section 4.10 suppression threshold (3).

    The data layer calls this after incrementing removal_count to decide whether to set the
    soft, reversible `suppressed` marker. Suppression is scenario-specific (the count is per
    recipient + chapter + scenario) and reversible (re-allow resets the count to 0, so it takes
    another 3 removals to re-suppress).
    """
    return removal_count >= SUPPRESSION_REMOVAL_THRESHOLD


def qualifies_for_cross_context(positive_count: int) -> bool:
    """True when a successful strategy may be offered in OTHER chapters (section 4.10).

    The cross-context gate: positive outcomes >= 2. A strategy that clears this in its own
    chapter is a candidate to surface in another chapter when it matches that activity's
    high-scoring dimension (the dimension test is matches_high_dimension). Negatives do not gate
    cross-context (only the positive track-record does, per section 4.10).
    """
    return positive_count >= CROSS_CONTEXT_MIN_POSITIVES


def matches_high_dimension(
    dimension_tags: Iterable[str], high_dimensions: Sequence[str]
) -> bool:
    """True when a strategy's dimensions intersect the activity's high-scoring ones.

    Section 4.4 step 7 / 4.10: a cross-context strategy is offered only when it "matches a
    high-scoring dimension" of the target activity. dimension_tags are the strategy's saved
    dimensions (its scenario's high base dimensions); high_dimensions are the dimensions of THIS
    activity scoring >= 3 (the HIGH_DIMENSION_SCORE cut). Any overlap is a match.
    """
    high = set(high_dimensions)
    return any(tag in high for tag in dimension_tags)
