""""What helped last time" data service (v3, ProductReview.md item 5).

The layer between the last-outcome route and Supabase for the prepare-time recall read
(GET /api/v1/chapters/{chapter}/last-outcome). It returns the family's OWN most recent prior
outcome in a chapter plus which saved strategy has worked, all read back from stored rows.

This is a READ of stored facts. It does NO scoring (it never runs the LCE, never re-derives a
tier, never computes an index): every field is a value already stored (the pulse outcome, the
copied tier, the named challenge dimension, the activity name) or a §4.10 PROMOTED flag read
from the saved strategy counts. So it is not an authoritative-engine change; it surfaces the
data the engines already produced.

PER-RECIPIENT ISOLATION + RLS (the board's law; Auth.md, Models.md): the read resolves ONE
recipient (profile.resolve_child_id, an explicit child_id verified owned, else the caller's
sole child) and scopes every query by user_id + child_id under get_anon_client(user.access_token),
so the recall is for exactly that recipient and a forged child_id is invisible under RLS (the
route maps the resolver's ChildNotFoundError to 404). A caller with no recipient yet, or a
chapter with no prior completed pulse, yields None and the app shows nothing.

BOUNDED reads (the every-list-is-capped rule): the two working reads (the chapter's pulses,
the chapter's saved strategies) carry a hard MAX_BOUNDED_ROWS `.limit(...)`, so a pathological
row count can never make a query unbounded. This is not an authoritative fold (§4.8), so the
cap never changes a number; it just protects the read. The most-recent-non-skipped pulse and
the most-positive promoted strategy are selected in Python over the capped, scoped rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.strategies import is_promoted
from app.models.last_outcome import LastOutcome
from app.models.seed import Tier
from app.services.pagination import MAX_BOUNDED_ROWS
from app.services.profile import _rows, resolve_child_id
from app.services.timestamps import parse_timestamptz

PULSE_RECORD_TABLE = "pulse_record"
ACTIVITY_RECORD_TABLE = "activity_record"
STRATEGY_LIBRARY_TABLE = "strategy_library_item"

# A skipped pulse is not an outcome to recall (it never happened as an experience): the recall
# finds the most recent NON-skipped pulse, so this code is excluded when choosing it.
SKIPPED_OUTCOME = "skipped"

# The outcomes §4.8 treats as POSITIVE for the pivot_helped fact: Well/Okay under any tier are
# positive; Difficult under a Continuity Pivot is ALSO positive (§4.8: the plan correctly
# protected the family). pivot_helped is true only for a positive outcome recorded under Pivot.
_POSITIVE_OUTCOMES = {"well", "okay"}


def get_last_outcome(
    user: AuthedUser,
    *,
    chapter: str,
    child_id: Optional[str] = None,
) -> Optional[LastOutcome]:
    """The recipient's most recent prior outcome in a chapter, or None for a first-time chapter.

    Reads stored facts only (no scoring):
      0. resolve the recipient (resolve_child_id; a forged child_id raises ChildNotFoundError,
         the route's 404). No recipient yet => None (the app shows nothing).
      1. read THIS recipient's pulses for the chapter (RLS + child_id scoped, capped), pick the
         most recent NON-skipped one. None (a first-time chapter, or only-skipped history) => None.
      2. read the activity_name of that pulse's activity_record (the human label), RLS-scoped.
      3. read THIS recipient's saved strategies for the chapter (RLS + child_id scoped, capped)
         and pick the §4.10 PROMOTED one with the most positives as worked_strategy (none yet =>
         null, no overclaim).
      4. compute pivot_helped from the stored outcome + tier (a fact, never a prediction).
    Returns the LastOutcome the app renders calmly, or None.
    """
    resolved_child_id = resolve_child_id(user, child_id)
    if resolved_child_id is None:
        return None

    pulse = _most_recent_completed_pulse(user, chapter, resolved_child_id)
    if pulse is None:
        return None

    activity_id = pulse.get("activity_id")
    activity_name = _activity_name(user, activity_id, resolved_child_id)
    outcome_code = pulse.get("outcome_code")
    tier_recommended = pulse.get("tier_recommended")
    worked_strategy = _worked_strategy_title(user, chapter, resolved_child_id)
    recorded_at = parse_timestamptz(pulse.get("created_at"))

    return LastOutcome(
        chapter=chapter,
        activity_name=activity_name or "",
        outcome_code=outcome_code,
        tier_recommended=tier_recommended,
        challenge_dimension=pulse.get("challenge_dimension"),
        worked_strategy=worked_strategy,
        pivot_helped=_pivot_helped(outcome_code, tier_recommended),
        recorded_at=recorded_at or datetime.now().astimezone(),
    )


# ---------------------------------------------------------------------------
# data access (RLS + child_id scoped, capped)
# ---------------------------------------------------------------------------


def _most_recent_completed_pulse(
    user: AuthedUser, chapter: str, child_id: str
) -> Optional[Dict[str, Any]]:
    """This recipient's most recent NON-skipped pulse in the chapter, or None.

    Reads the recipient's pulse_record rows for the chapter (RLS + child_id scoped, newest
    first, capped at MAX_BOUNDED_ROWS), then returns the first one whose outcome is not
    'skipped' (a skipped pulse is not an outcome to recall). The select carries the stored
    fields the recall surfaces (outcome, tier, challenge dimension, the activity id, the
    timestamp); the tier and challenge are the values copied onto the pulse, never re-derived.
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE)
        .select(
            "activity_id, outcome_code, tier_recommended, challenge_dimension, created_at"
        )
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("chapter", chapter)
        .order("created_at", desc=True)
        .limit(MAX_BOUNDED_ROWS)
        .execute()
    )
    # Defensive re-sort (a fake client or a null created_at must not reorder): newest first by
    # the parsed instant, then pick the most recent non-skipped outcome.
    rows.sort(key=_created_at_key, reverse=True)
    for row in rows:
        if (row.get("outcome_code") or "") != SKIPPED_OUTCOME:
            return row
    return None


def _activity_name(
    user: AuthedUser, activity_id: Any, child_id: str
) -> Optional[str]:
    """The activity_name of the recalled pulse's activity_record (RLS + child_id scoped), or None.

    A forged or missing activity_id matches nothing under RLS and yields None (the app then
    names the activity generically). Scoped by child_id too, so the label is always this
    recipient's own activity.
    """
    if not activity_id:
        return None
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("activity_name")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("id", str(activity_id))
        .limit(1)
        .execute()
    )
    if not rows:
        return None
    return rows[0].get("activity_name")


def _worked_strategy_title(
    user: AuthedUser, chapter: str, child_id: str
) -> Optional[str]:
    """The title of a §4.10 PROMOTED strategy for this recipient + chapter, or None.

    Reads the recipient's saved strategy_library_item rows for the chapter (RLS + child_id
    scoped, capped) and returns the title of the PROMOTED one (positives >= 2 AND more
    positives than negatives, the §4.10 rule via is_promoted) with the most positives, so the
    recall names a strategy the family's OWN data shows has worked. None when nothing has
    crossed the promotion bar (no overclaim from a single use) or the 0014 table is not applied
    (the read fails open to None, so the recall still returns the pulse facts).
    """
    try:
        rows = _rows(
            get_anon_client(user.access_token)
            .table(STRATEGY_LIBRARY_TABLE)
            .select("title, positive_count, negative_count, suppressed")
            .eq("user_id", user.id)
            .eq("child_id", child_id)
            .eq("chapter", chapter)
            .limit(MAX_BOUNDED_ROWS)
            .execute()
        )
    except Exception:  # noqa: BLE001 - the recall must never fail on the library read
        return None

    best_title: Optional[str] = None
    best_positives = -1
    for row in rows:
        if row.get("suppressed"):
            continue
        title = row.get("title")
        positives = int(row.get("positive_count") or 0)
        negatives = int(row.get("negative_count") or 0)
        if not title or not is_promoted(positives, negatives):
            continue
        if positives > best_positives:
            best_positives = positives
            best_title = title
    return best_title


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def _pivot_helped(outcome_code: Any, tier_recommended: Any) -> bool:
    """Whether the recalled outcome is the grounded "the Pivot worked here" fact.

    True ONLY when a POSITIVE outcome (the §4.8 sense: Well/Okay under any tier, OR Difficult
    under a Continuity Pivot, which §4.8 scores positively because the plan protected the
    family) was recorded under the Continuity Pivot tier. A stored-fact flag, never a
    prediction; false for any other combination.
    """
    code = (str(outcome_code or "")).strip().lower()
    tier = str(tier_recommended or "")
    if tier != Tier.PIVOT.value:
        return False
    # Under Pivot, Well/Okay are positive AND Difficult is also positive (§4.8), so any
    # non-skipped outcome under Pivot is a positive outcome the plan delivered.
    return code in _POSITIVE_OUTCOMES or code == "difficult"


def _created_at_key(row: Dict[str, Any]) -> datetime:
    """A sortable key for a pulse row's created_at (the epoch floor for an unparseable value)."""
    parsed = parse_timestamptz(row.get("created_at"))
    if parsed is None:
        return datetime.min.replace(tzinfo=None)
    # Normalise to a naive instant for a stable comparison (the rows are the same column).
    return parsed.replace(tzinfo=None)
