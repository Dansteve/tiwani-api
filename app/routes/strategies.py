"""v3 Strategy Library routes (the learning-layer mutations, Product.md section 4.10).

Thin HTTP only (HardRules/Api/SETUP.md): call the strategies service (which reads and writes
the strategy_library_item rows under RLS), serialize. Every route requires the current-user
dependency (401 without a valid bearer token; normal current-user, NOT allow-deleted: a
closed account cannot mutate its library); the writes are user-scoped through the service with
Supabase RLS as the backstop.

Registered under /api/v3 in main.py. The Strategy Library is evaluated server-side: the
auto-save, the promotion / suppression, and the cross-context surfacing happen in the plan and
pulse flows (sections 4.4 / 4.7). These routes are the COordinator's explicit actions on a saved
strategy: remove it (which suppresses it for its scenario after 3 removals), re-allow a suppressed
one, and dismiss a cross-context "Also worked in [chapter]" surfacing for one chapter. The
strategy is addressed by its library_item_id (carried on each PlanStrategy in the plan response);
a library_item_id the caller does not own is invisible under RLS and is a 404.

Endpoints:
  POST /api/v3/strategies/{library_item_id}/suppress
        record a removal of the strategy; once removed 3 times for its scenario it is
        suppressed (excluded next time). Returns the updated StrategyItemView. 404 if the item
        is not the caller's.
  POST /api/v3/strategies/{library_item_id}/allow
        re-allow a suppressed strategy (clear the marker, reset the removal count). Returns the
        updated StrategyItemView. 404 if not the caller's.
  POST /api/v3/strategies/{library_item_id}/dismiss-cross-context?chapter=<code>
        dismiss the strategy's "Also worked in [chapter]" surfacing for one chapter. Returns
        the updated StrategyItemView. 404 if not the caller's; 422 for an unknown chapter code.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthedUser, get_current_user
from app.models.chapters_v3 import Chapter
from app.models.strategy import StrategyItemView
from app.services import strategies as strategy_library

router = APIRouter()


@router.post("/strategies/{library_item_id}/suppress", response_model=StrategyItemView)
def suppress_strategy(
    library_item_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> StrategyItemView:
    """Record a removal of a strategy; suppress it for its scenario after 3 (section 4.10).

    The swipe-to-remove action (section 4.5): each call increments the strategy's removal count
    for its scenario, and the third removal sets the soft, reversible suppressed marker so the
    strategy is excluded from that scenario next time (scenario-specific; other scenarios are
    unaffected). Returns the updated state (suppressed flips true on the third call). 404 if the
    library item is unknown or not the caller's (it is invisible under RLS; the api does not
    confirm it exists for anyone).
    """
    try:
        return strategy_library.remove_strategy(user, library_item_id)
    except strategy_library.StrategyItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        ) from exc


@router.post("/strategies/{library_item_id}/allow", response_model=StrategyItemView)
def allow_strategy(
    library_item_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> StrategyItemView:
    """Re-allow a suppressed strategy (section 4.10 reversibility).

    Clears the suppressed marker and resets the removal count, so the strategy can appear again
    for its scenario and it takes another 3 removals to re-suppress. The Coordinator's "re-allow"
    that makes suppression reversible. Returns the updated state (suppressed false). 404 if the
    library item is unknown or not the caller's.
    """
    try:
        return strategy_library.allow_strategy(user, library_item_id)
    except strategy_library.StrategyItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        ) from exc


@router.post(
    "/strategies/{library_item_id}/dismiss-cross-context",
    response_model=StrategyItemView,
)
def dismiss_cross_context(
    library_item_id: str,
    chapter: Chapter = Query(
        ...,
        description=(
            "The chapter to dismiss this strategy's 'Also worked in [chapter]' surfacing in. "
            "Dismissible per chapter (section 4.10): other chapters are unaffected."
        ),
    ),
    user: AuthedUser = Depends(get_current_user),
) -> StrategyItemView:
    """Dismiss a strategy's "Also worked in [chapter]" surfacing for one chapter (section 4.10).

    Adds the chapter to the strategy's dismissed-cross-context set, so the cross-context
    suggestion does not reappear in that chapter; other chapters keep surfacing it. Idempotent.
    `chapter` is the stable chapter code (an unknown code is a 422 from the query validation).
    404 if the library item is unknown or not the caller's.
    """
    try:
        return strategy_library.dismiss_cross_context(user, library_item_id, chapter.value)
    except strategy_library.StrategyItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        ) from exc
