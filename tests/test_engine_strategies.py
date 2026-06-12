"""Table-driven tests for the pure Strategy Library rules (Product.md section 4.10).

These pin the section 4.10 thresholds to the exact numbers: promotion (positive outcomes >= 2
AND more positives than negatives), suppression (removed 3 times), the cross-context gate
(positive outcomes >= 2), and the high-dimension match. The rules are pure functions of counts +
dimensions (app/engines/strategies/rules.py), so no DB is needed (they are called directly).

The thresholds are AUTHORITATIVE and exact; a change to any of them needs the PRODUCT OWNER and
must update this table.
"""

from __future__ import annotations

import pytest

from app.engines.strategies import (
    CROSS_CONTEXT_MIN_POSITIVES,
    PROMOTION_MIN_POSITIVES,
    SUPPRESSION_REMOVAL_THRESHOLD,
    crosses_suppression_threshold,
    is_promoted,
    matches_high_dimension,
    qualifies_for_cross_context,
)


def test_thresholds_are_the_exact_section_4_10_numbers():
    # The named thresholds the api ranks on, pinned so a silent drift is caught.
    assert PROMOTION_MIN_POSITIVES == 2
    assert CROSS_CONTEXT_MIN_POSITIVES == 2
    assert SUPPRESSION_REMOVAL_THRESHOLD == 3


# ---------------------------------------------------------------------------
# Promotion: positive >= 2 AND positive > negative
# ---------------------------------------------------------------------------

PROMOTION_CASES = [
    # (positive, negative, expected_promoted)
    (0, 0, False),  # no outcomes yet
    (1, 0, False),  # one positive: below the >= 2 bar
    (2, 0, True),   # two positives, no negatives: promoted (the threshold case)
    (2, 1, True),   # two positives beat one negative: promoted
    (2, 2, False),  # equal positives and negatives: NOT promoted (not net-helped)
    (3, 4, False),  # more negatives than positives: NOT promoted
    (5, 4, True),   # cleared the bar and net-positive: promoted
    (2, 3, False),  # two positives but three negatives: NOT promoted
]


@pytest.mark.parametrize("positive, negative, expected", PROMOTION_CASES)
def test_promotion_rule(positive, negative, expected):
    assert is_promoted(positive, negative) is expected


def test_promotion_threshold_is_exactly_two_positives():
    # The boundary: one positive is not enough, two is, with no negatives to offset.
    assert is_promoted(1, 0) is False
    assert is_promoted(2, 0) is True


# ---------------------------------------------------------------------------
# Suppression: removed 3 times
# ---------------------------------------------------------------------------

SUPPRESSION_CASES = [
    (0, False),
    (1, False),
    (2, False),  # two removals: not yet suppressed
    (3, True),   # the third removal suppresses (the exact threshold)
    (4, True),
]


@pytest.mark.parametrize("removal_count, expected", SUPPRESSION_CASES)
def test_suppression_threshold(removal_count, expected):
    assert crosses_suppression_threshold(removal_count) is expected


def test_suppression_threshold_is_exactly_three_removals():
    # The boundary: two removals do not suppress, the third does.
    assert crosses_suppression_threshold(2) is False
    assert crosses_suppression_threshold(3) is True


# ---------------------------------------------------------------------------
# Cross-context gate: positive >= 2 (negatives do not gate it)
# ---------------------------------------------------------------------------

CROSS_CONTEXT_CASES = [
    (0, False),
    (1, False),
    (2, True),  # two positives qualifies for cross-context surfacing
    (5, True),
]


@pytest.mark.parametrize("positive, expected", CROSS_CONTEXT_CASES)
def test_cross_context_gate(positive, expected):
    assert qualifies_for_cross_context(positive) is expected


# ---------------------------------------------------------------------------
# High-dimension match: any overlap between a strategy's dims and the activity's high dims
# ---------------------------------------------------------------------------


def test_high_dimension_match_on_overlap():
    # The strategy's saved dimensions intersect the activity's high (>= 3) dimensions.
    assert matches_high_dimension(["sensory"], ["sensory", "human"]) is True
    assert matches_high_dimension(["temporal", "human"], ["human"]) is True


def test_high_dimension_no_match_without_overlap():
    assert matches_high_dimension(["temporal"], ["sensory", "human"]) is False
    # No high dimensions on the target activity: nothing to match.
    assert matches_high_dimension(["sensory"], []) is False
    # No saved dimensions on the strategy: nothing to match.
    assert matches_high_dimension([], ["sensory"]) is False
