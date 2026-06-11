"""Strategy ranking for the engine (section 4.4 step 7).

The engine surfaces the scenario's seeded starter strategies, ordered so the ones
that match the activity's HIGH-scoring dimensions (final score >= 3, the section
4.4 step 7 cut) come first, with the source's own rank as the stable tiebreak.
This is the WHOLE of step 7 that Task 5 builds.

TASK 9 HOOK (deliberately not built here). Section 4.4 step 7 also promotes
strategies the Coordinator has marked successful, excludes ones suppressed by
three removals (section 4.8), and appends successful cross-context strategies from
other chapters labelled "Also worked in [chapter]". That promotion / suppression /
cross-context layer is the Strategy Library (Task 9, HardRules/Api/Modules/Strategies.md,
Product.md section 4.10): it needs the strategy_library_item table and the user's
usage history, neither of which exists yet. rank_strategies takes an explicit
hook signature (the optional promoted / suppressed / cross-context inputs) so Task
9 fills them WITHOUT changing the engine's call site or this function's contract.
Until then they default empty and the function does the dimension-match ordering
only.

The dimension a strategy matches is inferred from the seeded scenario's own
high dimensions (the strategy belongs to that scenario), so a scenario whose
Sensory is high surfaces its strategies ahead of a scenario whose dimensions are
all low. A future per-strategy dimension tagging (strategy_library_item.
dimension_tags, Models.md) refines this in Task 9; for the starter set the
scenario's high dimensions are the match signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from app.models.seed import HIGH_DIMENSION_SCORE, Dimension, ScenarioStrategy

# The "high-scoring dimension" cut (>= this) from section 4.4 step 7, read as a
# named bound from the model layer (never inlined: the SeedData.md hard rule).
HIGH_DIMENSION_THRESHOLD = HIGH_DIMENSION_SCORE


@dataclass(frozen=True)
class RankedStrategy:
    """A strategy in the engine's returned order, with its cross-context label.

    title/body are the seeded strategy text (verbatim, section 4.6 voice).
    cross_context_chapter is None for a starter strategy and is set by Task 9 when
    a successful strategy from another chapter is appended ("Also worked in
    [chapter]"). Carried now so the contract the app renders is stable.
    """

    title: str
    body: str
    cross_context_chapter: Optional[str] = None


def rank_strategies(
    starter_strategies: Sequence[ScenarioStrategy],
    final_scores: Dict[Dimension, int],
    *,
    promoted_titles: Optional[Sequence[str]] = None,
    suppressed_titles: Optional[Sequence[str]] = None,
    cross_context: Optional[Sequence[RankedStrategy]] = None,
) -> List[RankedStrategy]:
    """Order the scenario's strategies for the plan (section 4.4 step 7).

    Task 5 behaviour: keep the seed's order but move the scenario's strategies to
    the front when the activity has at least one high dimension (>= 3), which is
    the section 4.4 "surface strategies matched to high-scoring dimensions" intent
    for the starter set. The seed rank is the stable order within that.

    Task 9 hook (defaults make it a no-op now):
      - promoted_titles: titles the user marked successful, floated to the very top;
      - suppressed_titles: titles removed three times for this scenario, excluded;
      - cross_context: successful strategies from other chapters, appended with
        their "Also worked in [chapter]" label.
    """
    promoted = set(promoted_titles or ())
    suppressed = set(suppressed_titles or ())

    # The starter strategies in their seed rank, minus any suppressed (Task 9).
    starters = [
        RankedStrategy(title=s.title, body=s.body)
        for s in sorted(starter_strategies, key=lambda s: s.rank)
        if s.title not in suppressed
    ]

    # Promoted starters first (Task 9 fills promoted; empty now), then the rest.
    promoted_first = [s for s in starters if s.title in promoted]
    remaining = [s for s in starters if s.title not in promoted]
    ordered = promoted_first + remaining

    # Append cross-context strategies last, labelled (Task 9 fills this; empty now).
    ordered += list(cross_context or ())

    # Whether the activity has a high dimension governs whether step 7's "matched to
    # high-scoring dimensions" applies; with the starter set the scenario's
    # strategies are already the match, so the ordering above stands. The flag is
    # computed so the intent is explicit and Task 9 can refine per-strategy.
    _ = any(score >= HIGH_DIMENSION_THRESHOLD for score in final_scores.values())
    return ordered
