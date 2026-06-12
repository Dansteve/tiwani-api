"""Strategy Library: strategies that get better with use (Product.md section 4.10).

The learning layer's PURE rules: promotion, suppression, and cross-context matching as
deterministic functions of a saved item's counts + dimension tags. No DB, no clock, no
randomness here (the same way app/engines/alerts is pure), so the thresholds are exhaustively
table-testable. The data layer (app/services/strategies.py) reads/writes the
strategy_library_item rows (migration 0014) and applies these rules; the rules NEVER change a
score, total, tier, or the LCI: they only decide the strategy ranking ORDER (Engine.md step 7).

Module file: HardRules/Api/Modules/Strategies.md. Data object: Models.md (strategy_library_item).

The exact rules to the number (Product.md section 4.10, AUTHORITATIVE):
  - promotion (appears first next time): positive outcomes >= 2 AND more positives than
    negatives, specific to that recipient and scenario
  - suppression (excluded next time): removed 3 times for the same strategy + scenario;
    scenario-specific and reversible
  - outcome attribution (MVP): a Pulse outcome applies EQUALLY to every strategy in that plan
    (a deliberate MVP simplification, Q8; do not "fix" without the PRODUCT OWNER)
  - cross-context surfacing: a strategy with positive outcomes >= 2 is offered in other chapters
    when it matches a high-scoring dimension, labelled "Also worked in [chapter]", dismissible
    per chapter

Layout:
  rules.py   the pure section 4.10 predicates + the named thresholds (is_promoted,
             crosses_suppression_threshold, qualifies_for_cross_context, matches_high_dimension).
"""

from app.engines.strategies.rules import (
    CROSS_CONTEXT_MIN_POSITIVES,
    PROMOTION_MIN_POSITIVES,
    SUPPRESSION_REMOVAL_THRESHOLD,
    crosses_suppression_threshold,
    is_promoted,
    matches_high_dimension,
    qualifies_for_cross_context,
)

__all__ = [
    "is_promoted",
    "crosses_suppression_threshold",
    "qualifies_for_cross_context",
    "matches_high_dimension",
    "PROMOTION_MIN_POSITIVES",
    "CROSS_CONTEXT_MIN_POSITIVES",
    "SUPPRESSION_REMOVAL_THRESHOLD",
]
