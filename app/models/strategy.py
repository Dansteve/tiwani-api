"""Strategy Library pydantic schemas (v3): the suppress / re-allow response contract.

The cross-repo contract for the Strategy Library mutation endpoints (Product.md section
4.10, HardRules/Api/Modules/Strategies.md). The app drives the remove / re-allow actions
from a strategy's library_item_id (carried on each PlanStrategy, app/models/plan.py) and
reads back the updated state here so it can reflect whether the strategy is now suppressed.

  - StrategyItemView: one saved strategy_library_item after a suppress / re-allow, the
    state the app renders: {library_item_id, chapter, scenario_type, title, suppressed,
    promoted, removal_count, positive_count, negative_count}. suppressed is the soft,
    reversible per-scenario marker (true once removed 3 times, false after a re-allow);
    promoted is the cached section 4.10 promotion flag.

The stored shape (the DB row) is strategy_library_item (migration 0014, the per-recipient
learning row); StrategyItemView is the trimmed response the app mirrors, not the raw row.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrategyItemView(BaseModel):
    """One saved strategy's state after a suppress / re-allow (the app's mirror).

    library_item_id is the saved item id (the same id the PlanStrategy carries). chapter +
    scenario_type say which scenario this strategy belongs to (suppression is scenario-
    specific). suppressed is the reversible exclusion marker; promoted is the cached
    promotion flag; the counts are the current learning state. The app reads suppressed to
    show/hide the strategy and to flip the remove control to a re-allow.
    """

    model_config = ConfigDict(frozen=True)

    library_item_id: str
    chapter: str
    scenario_type: str
    title: str
    suppressed: bool
    promoted: bool
    removal_count: int = Field(..., ge=0)
    positive_count: int = Field(..., ge=0)
    negative_count: int = Field(..., ge=0)
