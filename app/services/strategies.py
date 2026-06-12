"""Strategy Library data + orchestration service (v3, Product.md section 4.10).

The layer between the engine/pulse/strategy routes and Supabase for the learning layer.
It owns the strategy_library_item reads and writes (migration 0014) and turns a recipient's
saved-strategy history into the promotion / suppression / cross-context inputs the LCE step 7
ranker consumes. The pure rules (the section 4.10 thresholds) live in app/engines/strategies;
this module reads the rows, applies those rules, and writes the counts. It NEVER changes a
score, total, tier, or the LCI: it only reorders / filters / appends strategies and updates
counts.

PER-RECIPIENT ISOLATION (the board's law). Every read and write is scoped to one recipient
(user_id + child_id), so a library item for child A never affects child B's ranking or counts.
The auto-save, the outcome update, the ranking inputs, and the suppress/allow operations all
carry child_id; a missing child_id scope would mix two recipients (the isolation rule forbids
it), exactly as the dashboard / LCI / alerts are scoped.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every query runs through
get_anon_client(user.access_token), so PostgREST carries the user's JWT and Row Level Security
scopes every read/write to that user's rows (migration 0014's strategy_library_item_*_own
policies). A library_item_id the caller does not own is invisible under RLS and reads as
not-found.

GRACEFUL DEGRADATION before the migration is applied (the 0014 banner is PENDING OWNER APPLY):
the auto-save and the outcome update are wrapped non-interrupting at their call sites (the plan
and the pulse), and the ranking-input reads fail open to "no learning yet", so the plan always
returns the seeded starter strategies whether or not the table exists yet. The engine never
depends on this table.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.strategies import (
    crosses_suppression_threshold,
    is_promoted,
    matches_high_dimension,
    qualifies_for_cross_context,
)
from app.models.chapters import CHAPTER_DISPLAY_NAMES, Chapter
from app.models.strategy import StrategyItemView
from app.services.profile import _first, _rows

STRATEGY_LIBRARY_TABLE = "strategy_library_item"

logger = logging.getLogger(__name__)


class StrategyItemNotFoundError(Exception):
    """Raised when a library_item_id is unknown or not the caller's (route maps to 404).

    RLS scopes the read to the caller, so a library_item_id for another user matches nothing
    and surfaces here as not-found: the route returns 404 without confirming the row exists
    for anyone (the error-contract rule, do not leak another user's data).
    """


# ---------------------------------------------------------------------------
# the ranking inputs (read by app/services/plans.py before shaping the plan)
# ---------------------------------------------------------------------------


class StrategyLibraryInputs:
    """The section 4.10 ranking inputs for ONE recipient + scenario, plus cross-context.

    Carries everything the plan service needs to (a) reorder/filter the engine's ranked
    starter strategies (promoted_titles first, suppressed_titles excluded) and (b) append
    the cross-context "Also worked in [chapter]" matches, and (c) attach each strategy's
    library_item_id and also_worked_in list to the response. It is built per plan from the
    recipient's saved items for the activity's own scenario (promotion/suppression) plus the
    recipient's successful items from OTHER chapters (cross-context).
    """

    def __init__(
        self,
        *,
        promoted_titles: List[str],
        suppressed_titles: List[str],
        item_id_by_title: Dict[str, str],
        cross_context: List["CrossContextStrategy"],
    ):
        self.promoted_titles = promoted_titles
        self.suppressed_titles = suppressed_titles
        self.item_id_by_title = item_id_by_title
        self.cross_context = cross_context


class CrossContextStrategy:
    """One cross-context strategy offered in this chapter ("Also worked in [chapter]").

    title/body are the saved strategy text; source_chapter is the chapter it succeeded in
    (the "Also worked in [chapter]" label resolves to its display name); library_item_id is
    the saved item so the app can dismiss it for this chapter.
    """

    def __init__(self, *, title: str, body: str, source_chapter: str, library_item_id: str):
        self.title = title
        self.body = body
        self.source_chapter = source_chapter
        self.library_item_id = library_item_id


def empty_inputs() -> StrategyLibraryInputs:
    """The no-learning-yet inputs (a fresh recipient, or the table not applied yet).

    Used as the fail-open default so the plan always returns the seeded starter order when
    there is no library history (or the 0014 table is not applied): no promotion, no
    suppression, no cross-context, no id mapping.
    """
    return StrategyLibraryInputs(
        promoted_titles=[],
        suppressed_titles=[],
        item_id_by_title={},
        cross_context=[],
    )


def ranking_inputs_for_plan(
    user: AuthedUser,
    *,
    child_id: str,
    chapter: str,
    scenario_type: str,
    high_dimensions: Sequence[str],
) -> StrategyLibraryInputs:
    """Build ONE recipient's section 4.10 ranking inputs for the activity being planned.

    Two reads, both scoped to this recipient (the isolation rule):
      1. the saved items for THIS (chapter, scenario_type): each promoted item's title floats
         first, each suppressed item's title is excluded, and every saved item's id is mapped
         by title so the response can carry library_item_id (so the app can remove it);
      2. the recipient's successful items (positive outcomes >= 2) in OTHER chapters whose
         saved dimensions match one of THIS activity's high-scoring dimensions (>= 3) and that
         have NOT been dismissed in this chapter, as the cross-context "Also worked in
         [chapter]" appendix.
    Fails open (empty inputs) on any read error, so a missing table or a transient failure
    never blocks the plan (the engine's starter strategies still return).
    """
    try:
        scenario_items = _scenario_items(user, child_id, chapter, scenario_type)
    except Exception:  # noqa: BLE001 - the plan must never fail on the library read
        logger.exception("strategy library scenario read failed (%s/%s)", chapter, scenario_type)
        return empty_inputs()

    promoted_titles: List[str] = []
    suppressed_titles: List[str] = []
    item_id_by_title: Dict[str, str] = {}
    for row in scenario_items:
        title = row.get("title")
        item_id = row.get("id")
        if not title or item_id is None:
            continue
        item_id_by_title[title] = str(item_id)
        if row.get("suppressed"):
            suppressed_titles.append(title)
            continue  # a suppressed strategy is excluded, never also promoted
        if _row_is_promoted(row):
            promoted_titles.append(title)

    try:
        cross_context = _cross_context_matches(
            user, child_id, chapter, scenario_type, high_dimensions
        )
    except Exception:  # noqa: BLE001 - cross-context is additive; never fail the plan
        logger.exception("strategy library cross-context read failed (%s)", chapter)
        cross_context = []

    return StrategyLibraryInputs(
        promoted_titles=promoted_titles,
        suppressed_titles=suppressed_titles,
        item_id_by_title=item_id_by_title,
        cross_context=cross_context,
    )


def _cross_context_matches(
    user: AuthedUser,
    child_id: str,
    target_chapter: str,
    target_scenario: str,
    high_dimensions: Sequence[str],
) -> List[CrossContextStrategy]:
    """The recipient's successful OTHER-chapter strategies matching a high dimension here.

    Reads this recipient's whole library (RLS + child_id scoped), then keeps the items that:
      - are in a DIFFERENT chapter than the target (cross-context is across chapters);
      - have positive outcomes >= 2 (the section 4.10 cross-context gate);
      - are NOT suppressed;
      - have a saved dimension matching one of the target activity's high dimensions (>= 3);
      - have NOT been dismissed for the target chapter (dismissible per chapter).
    De-duplicated by title (a strategy successful in several other chapters surfaces once,
    labelled with the first matching source chapter), so the appendix does not repeat a title.
    The target scenario's own items are excluded (they are handled by promotion/suppression).
    """
    if not high_dimensions:
        return []
    all_items = _all_items(user, child_id)
    seen_titles: set = set()
    matches: List[CrossContextStrategy] = []
    for row in all_items:
        source_chapter = row.get("chapter")
        title = row.get("title")
        item_id = row.get("id")
        if not title or item_id is None or source_chapter == target_chapter:
            continue
        if row.get("suppressed"):
            continue
        if not qualifies_for_cross_context(int(row.get("positive_count") or 0)):
            continue
        if not matches_high_dimension(row.get("dimension_tags") or [], high_dimensions):
            continue
        if target_chapter in (row.get("cross_context_dismissed_chapters") or []):
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)
        matches.append(
            CrossContextStrategy(
                title=title,
                body=row.get("description") or "",
                source_chapter=source_chapter,
                library_item_id=str(item_id),
            )
        )
    return matches


def cross_context_label(source_chapter: str) -> str:
    """The "Also worked in [chapter]" label text for a cross-context source chapter.

    Resolves the chapter code to its display name (Family Life & Routine, etc.) so the app
    can render the section 4.10 label without re-keying the chapter vocabulary.
    """
    try:
        return f"Also worked in {CHAPTER_DISPLAY_NAMES[Chapter(source_chapter)]}"
    except (ValueError, KeyError):
        return f"Also worked in {source_chapter}"


# ---------------------------------------------------------------------------
# auto-save (called from app/services/plans.py after a plan is produced)
# ---------------------------------------------------------------------------


def auto_save_plan_strategies(
    user: AuthedUser,
    *,
    child_id: str,
    chapter: str,
    scenario_type: str,
    strategies: Sequence[Dict[str, Any]],
    high_dimensions: Sequence[str],
) -> None:
    """Upsert each plan strategy as a library item for this recipient + scenario (idempotent).

    Section 4.10: "every strategy in a completed plan is saved automatically and tagged to its
    chapter and scenario." Called after the engine produces the ranked strategies; for each
    starter strategy (the cross-context appendix is NOT re-saved here, it already lives under
    its own scenario), it INSERTs a strategy_library_item if absent or leaves the existing one
    untouched (idempotent on a re-plan via the (user_id, child_id, chapter, scenario_type,
    title) unique key, so the counts accumulate across plans rather than resetting). The saved
    dimension_tags are the scenario's high dimensions (>= 3), the cross-context match signal.

    Non-interrupting: wrapped so a write failure (or the table not applied yet) never fails the
    plan, which has already been computed and stored. dimension_tags is the same for every
    strategy of a scenario (the scenario's high dimensions), so a strategy carries its
    scenario's pressure signal for the cross-context test.
    """
    try:
        existing = {
            r.get("title")
            for r in _scenario_items(user, child_id, chapter, scenario_type)
            if r.get("title")
        }
    except Exception:  # noqa: BLE001 - never fail the plan on the library
        logger.exception("strategy library auto-save read failed (%s/%s)", chapter, scenario_type)
        return

    client = get_anon_client(user.access_token)
    tags = list(high_dimensions)
    for strategy in strategies:
        title = strategy.get("title")
        if not title or title in existing:
            continue
        # A cross-context strategy appended from another chapter is not a strategy OF this
        # scenario; it is saved under its own scenario already, so skip it here.
        if strategy.get("also_worked_in_chapter"):
            continue
        insert_row = {
            "user_id": user.id,
            "child_id": child_id,
            "chapter": chapter,
            "scenario_type": scenario_type,
            "title": title,
            "description": strategy.get("detail") or "",
            "dimension_tags": tags,
        }
        try:
            client.table(STRATEGY_LIBRARY_TABLE).insert(insert_row).execute()
            existing.add(title)
        except Exception:  # noqa: BLE001 - a duplicate or table-absent insert must not fail the plan
            logger.exception("strategy library auto-save insert failed for '%s'", title)


# ---------------------------------------------------------------------------
# outcome counts (called from app/services/pulse.py on pulse completion, Task 6 path)
# ---------------------------------------------------------------------------


def apply_pulse_outcome(
    user: AuthedUser,
    *,
    child_id: str,
    chapter: str,
    scenario_type: str,
    plan_strategies: Sequence[Dict[str, Any]],
    outcome_code: str,
) -> None:
    """Apply a Pulse outcome EQUALLY to every saved strategy in the pulsed plan (section 4.10).

    The MVP equal-attribution rule (section 4.10 / Q8, do NOT change without the PRODUCT
    OWNER): a Well/Okay outcome increments positive_count on every library item that was in
    this plan's strategy list; a Difficult outcome increments negative_count; a skipped pulse
    moves neither. promoted is recomputed from the new counts (is_promoted) so the ranker can
    read it directly. Scoped to the activity's OWN recipient + chapter + scenario (passed from
    the stored activity_record), so a pulse for child A never touches child B's counts.

    Non-interrupting at the call site (the pulse has already been recorded and the LCI
    recomputed); this only updates the learning counts. An unknown outcome_code (neither
    positive nor negative nor skipped) is treated as no-effect.
    """
    delta = _outcome_delta(outcome_code)
    if delta is None:
        return  # skipped or unknown: equal attribution moves nothing

    positive_inc, negative_inc = delta
    titles = [s.get("title") for s in plan_strategies if s.get("title")]
    if not titles:
        return

    rows = _scenario_items(user, child_id, chapter, scenario_type)
    by_title = {r.get("title"): r for r in rows}
    client = get_anon_client(user.access_token)
    for title in titles:
        row = by_title.get(title)
        if row is None:
            continue
        new_positive = int(row.get("positive_count") or 0) + positive_inc
        new_negative = int(row.get("negative_count") or 0) + negative_inc
        item_id = row.get("id")
        if item_id is None:
            continue
        client.table(STRATEGY_LIBRARY_TABLE).update(
            {
                "positive_count": new_positive,
                "negative_count": new_negative,
                "promoted": is_promoted(new_positive, new_negative),
            }
        ).eq("user_id", user.id).eq("child_id", child_id).eq("id", item_id).execute()


def apply_pulse_outcome_safe(
    user: AuthedUser,
    *,
    child_id: Optional[str],
    chapter: Optional[str],
    scenario_type: Optional[str],
    plan_strategies: Sequence[Dict[str, Any]],
    outcome_code: str,
) -> None:
    """apply_pulse_outcome wrapped so it NEVER raises into the pulse flow.

    The Strategy Library count update is a background learning step (the same posture as the
    Erosion Alert evaluation, section 4.10 / KB 1.6): the pulse and the LCI recompute have
    already succeeded, so a failure here (or the 0014 table not applied yet) is logged and
    swallowed rather than failing the recorded pulse. Skips silently if the activity carried no
    child_id / chapter / scenario (an old record predating the wiring).
    """
    if not child_id or not chapter or not scenario_type:
        return
    try:
        apply_pulse_outcome(
            user,
            child_id=child_id,
            chapter=chapter,
            scenario_type=scenario_type,
            plan_strategies=plan_strategies,
            outcome_code=outcome_code,
        )
    except Exception:  # noqa: BLE001 - the learning update must never fail the pulse
        logger.exception("strategy library outcome update failed (%s/%s)", chapter, scenario_type)


# ---------------------------------------------------------------------------
# suppress / re-allow (POST /api/v1/strategies/{id}/suppress | /allow)
# ---------------------------------------------------------------------------


def remove_strategy(user: AuthedUser, library_item_id: str) -> StrategyItemView:
    """Record a removal of a strategy; suppress it for its scenario after 3 (section 4.10).

    The swipe-to-remove path (Product.md section 4.5): each call increments removal_count for
    this saved item, and once the count reaches the section 4.10 threshold (3) the soft,
    reversible `suppressed` marker is set, so the strategy is excluded from this scenario next
    time. Scenario-specific (the item is one recipient + chapter + scenario) and reversible
    (allow_strategy clears it). RLS scopes the read/write to the caller; a library_item_id the
    caller does not own raises StrategyItemNotFoundError (404). Returns the updated state so the
    route can report the new suppressed flag.
    """
    row = _owned_item(user, library_item_id)
    if row is None:
        raise StrategyItemNotFoundError("No such strategy for this user")

    new_removal_count = int(row.get("removal_count") or 0) + 1
    suppressed = crosses_suppression_threshold(new_removal_count)
    updated = _update_item(
        user,
        library_item_id,
        {"removal_count": new_removal_count, "suppressed": suppressed},
    )
    return _to_item_view(updated)


def allow_strategy(user: AuthedUser, library_item_id: str) -> StrategyItemView:
    """Re-allow a suppressed strategy (section 4.10 reversibility): clear it and reset the count.

    Clears the soft `suppressed` marker and resets removal_count to 0, so the strategy can
    appear again for its scenario and it takes another 3 removals to re-suppress (reversible by
    design, the Coordinator's "re-allow"). RLS scopes the write to the caller; a library_item_id
    the caller does not own raises StrategyItemNotFoundError (404). Returns the updated state.
    """
    row = _owned_item(user, library_item_id)
    if row is None:
        raise StrategyItemNotFoundError("No such strategy for this user")
    updated = _update_item(user, library_item_id, {"suppressed": False, "removal_count": 0})
    return _to_item_view(updated)


def dismiss_cross_context(
    user: AuthedUser, library_item_id: str, chapter: str
) -> StrategyItemView:
    """Dismiss a strategy's "Also worked in [chapter]" surfacing for one chapter (section 4.10).

    Adds the chapter code to the item's cross_context_dismissed_chapters set, so the
    cross-context suggestion does not reappear in that chapter (dismissible per chapter). Other
    chapters are unaffected. RLS scopes the write to the caller; a library_item_id the caller
    does not own raises StrategyItemNotFoundError (404). Idempotent: dismissing an
    already-dismissed chapter leaves the set unchanged. Returns the updated state.
    """
    row = _owned_item(user, library_item_id)
    if row is None:
        raise StrategyItemNotFoundError("No such strategy for this user")
    dismissed = list(row.get("cross_context_dismissed_chapters") or [])
    if chapter not in dismissed:
        dismissed.append(chapter)
    updated = _update_item(
        user, library_item_id, {"cross_context_dismissed_chapters": dismissed}
    )
    return _to_item_view(updated)


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------


def _scenario_items(
    user: AuthedUser, child_id: str, chapter: str, scenario_type: str
) -> List[Dict[str, Any]]:
    """This recipient's saved items for one (chapter, scenario_type), RLS + child_id scoped."""
    client = get_anon_client(user.access_token)
    return _rows(
        client.table(STRATEGY_LIBRARY_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("chapter", chapter)
        .eq("scenario_type", scenario_type)
        .execute()
    )


def _all_items(user: AuthedUser, child_id: str) -> List[Dict[str, Any]]:
    """This recipient's whole library (RLS + child_id scoped), for the cross-context scan."""
    client = get_anon_client(user.access_token)
    return _rows(
        client.table(STRATEGY_LIBRARY_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .execute()
    )


def _owned_item(user: AuthedUser, library_item_id: str) -> Optional[Dict[str, Any]]:
    """The caller's library item by id (RLS-scoped), or None if it is not theirs.

    Filters by id AND user_id under the caller's token, so RLS plus the explicit user_id filter
    make another user's item unreachable: a forged id matches nothing and returns None (the
    route maps that to 404 without confirming the row exists for anyone).
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(STRATEGY_LIBRARY_TABLE)
        .select("*")
        .eq("id", library_item_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )


def _update_item(
    user: AuthedUser, library_item_id: str, fields: Dict[str, Any]
) -> Dict[str, Any]:
    """Update the caller's library item by id and return the updated row (RLS-scoped).

    The update scopes by (id, user_id), so a caller can only ever update their own item. If the
    update returns no representation, the row is read back under RLS so the caller always gets
    the canonical updated state.
    """
    client = get_anon_client(user.access_token)
    updated = _first(
        client.table(STRATEGY_LIBRARY_TABLE)
        .update(fields)
        .eq("id", library_item_id)
        .eq("user_id", user.id)
        .execute()
    )
    if updated is not None:
        return updated
    confirmed = _owned_item(user, library_item_id)
    if confirmed is None:
        raise StrategyItemNotFoundError("No such strategy for this user")
    return confirmed


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def _to_item_view(row: Dict[str, Any]) -> StrategyItemView:
    """Shape a stored strategy_library_item row into the StrategyItemView the app reads.

    Carries the identity (id, chapter, scenario_type, title), the reversible suppressed marker,
    the cached promotion flag, and the current counts, so the app can reflect the new state
    after a suppress / re-allow. promoted is read from the row's cached column (kept in step
    with the counts on every outcome update).
    """
    return StrategyItemView(
        library_item_id=str(row.get("id")),
        chapter=row.get("chapter") or "",
        scenario_type=row.get("scenario_type") or "",
        title=row.get("title") or "",
        suppressed=bool(row.get("suppressed")),
        promoted=bool(row.get("promoted")),
        removal_count=int(row.get("removal_count") or 0),
        positive_count=int(row.get("positive_count") or 0),
        negative_count=int(row.get("negative_count") or 0),
    )


def _row_is_promoted(row: Dict[str, Any]) -> bool:
    """Whether a saved row is promoted, from its counts (the rule, not the cached flag).

    Reads positive_count/negative_count and applies the section 4.10 promotion rule directly,
    so the ranker is correct even if the cached `promoted` column is ever stale (the counts are
    the source of truth). The cached column is maintained on every outcome update for reads that
    prefer it.
    """
    return is_promoted(int(row.get("positive_count") or 0), int(row.get("negative_count") or 0))


def _outcome_delta(outcome_code: str) -> Optional[tuple]:
    """(positive_inc, negative_inc) for a Pulse outcome, or None for skipped/unknown.

    Section 4.10 outcome attribution: Well and Okay are positive outcomes (the plan helped),
    Difficult is a negative outcome, a skipped pulse (and any unknown code) moves neither count.
    The outcome vocabulary matches the pulse_record outcome_code (well / okay / difficult /
    skipped), compared case-insensitively.
    """
    code = (outcome_code or "").strip().lower()
    if code in ("well", "okay"):
        return (1, 0)
    if code == "difficult":
        return (0, 1)
    return None
