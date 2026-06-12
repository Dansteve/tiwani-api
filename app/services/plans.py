"""Preparation Plan data + orchestration service (v3).

The layer between the plan routes and Supabase for the Life Continuity Engine
(Product.md section 4.4). It runs the engine (steps 1 to 7 + 10, in app/engines/lce),
then performs the persistence/clock steps the engine itself does not:
  - step 8: STORE the activity_record and CONFIRM the write before returning;
  - step 9: SCHEDULE the Pulse (the activity date + 2 hours, or 09:00 the next day
    if no date is set). The Pulse notification itself is Task 6; this only persists
    scheduled_pulse_at.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): the child profile
is read and the activity_record is written through get_anon_client(user.access_token),
so PostgREST carries the user's JWT and Row Level Security scopes every query to
that user's rows. The insert sets user_id and child_id from the resolved session
and the user's own care recipient, never from the client.

The engine is deterministic and reads the seeded scenario/tag rows; no scoring
happens here (the route is thin, the engine is pure). This service only fetches
the inputs, calls run_engine, writes the result, and shapes the PreparationPlan.

READING STORED PLANS BACK (no re-run): list_stored_plans and get_stored_plan serve
the two READ endpoints (GET /api/v1/plans and GET /api/v1/plans/{activity_id}). They
read the caller's activity_record rows under RLS and return the STORED values, never
calling run_engine again. get_stored_plan reconstructs the PreparationPlan shape from
the stored columns (the final scores, total, tier, the JSON strategies, the scheduled
pulse time); dimension_explanations is not stored, so it is null on a stored read (the
model allows it). The pulse status on a summary is derived the same way the pending
list is (section 4.7), reading the caller's pulse_record activity ids.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.lce import EngineResult, run_engine
from app.models.plan import (
    ActivityOption,
    AlsoWorkedIn,
    DimensionExplanations,
    DimensionScores,
    PlanStrategy,
    PlanSummary,
    PreparationPlan,
)
from app.models.seed import HIGH_DIMENSION_SCORE, Dimension, Tier
from app.seed import load_seed
from app.services import strategies as strategy_library
from app.services.profile import _first, _rows, get_child, get_child_by_id
from app.services.timestamps import parse_timestamptz

ACTIVITY_RECORD_TABLE = "activity_record"
PULSE_RECORD_TABLE = "pulse_record"

# Section 4.4 step 9 Pulse-scheduling constants. The Pulse is due the activity date
# + this many hours; with no date it is due at the default time the next day. These
# are SCHEDULING parameters (a clock concern), deliberately kept in the service and
# NOT in the engine package, so the engine source stays free of any numeric literal
# (the SeedData.md hard rule / the pytest guard over app/engines/lce).
PULSE_DELAY_HOURS = 2
PULSE_DEFAULT_TIME = time(hour=9, minute=0)


class NoCareRecipientError(Exception):
    """Raised when the user has no care recipient to plan for (route maps to 409)."""


class PlanNotFoundError(Exception):
    """Raised when an activity_id is unknown or not the caller's (route maps to 404).

    RLS scopes the read to the caller, so a forged id for another user matches nothing
    and surfaces here as not-found: the route returns 404 without confirming the row
    exists for anyone (the error-contract rule, do not leak another user's data).
    """


def prepare_plan(
    user: AuthedUser,
    *,
    chapter: str,
    activity_code: str,
    today_flags: List[str],
    activity_date: Optional[date_type] = None,
    context_note: Optional[str] = None,
    now: Optional[datetime] = None,
    child_id: Optional[str] = None,
) -> PreparationPlan:
    """Run the engine for the user's care recipient, store the record, return the plan.

    Steps, in order (section 4.4):
      0. fetch the care recipient to plan for (the SL code + permanent tags the engine
         scores from). With child_id given, the plan is prepared for THAT recipient
         (verified owned under RLS); with child_id omitted it is the caller's sole
         recipient (the back-compat default). No recipient (or a child_id the caller
         does not own) => NoCareRecipientError (the route maps to 409).
      1 to 7 + 10. run_engine (pure, seeded rows).
      9. compute scheduled_pulse_at (activity date + 2h, or 09:00 next day).
      8. INSERT the activity_record and CONFIRM the write (re-read if the insert
         returns no representation), so the plan is never returned for an unsaved
         record.
      10. shape and return the PreparationPlan.

    child_id is the multi-recipient scope (Docs/FeatureDecisions.md, the design note):
    the app sends the ACTIVE recipient's id so a plan is prepared for the recipient
    currently being viewed. It is resolved under RLS through get_child_by_id, so a
    child_id the caller does not own returns None and surfaces as NoCareRecipientError
    (the api never confirms another user's recipient exists). Omitted child_id keeps
    the existing sole-child behaviour, so callers that send none are unchanged.

    now is injectable for tests (the schedule's "next day" base); it defaults to
    the current time and is the ONLY clock the flow uses (the scoring never reads a
    clock).
    """
    child = get_child_by_id(user, child_id) if child_id is not None else get_child(user)
    if child is None:
        raise NoCareRecipientError("No care recipient to prepare a plan for")

    support_level_code = child.get("support_level_code")
    permanent_tags = list(child.get("tags") or [])

    result = run_engine(
        chapter=chapter,
        activity_code=activity_code,
        support_level_code=support_level_code,
        permanent_tags=permanent_tags,
        today_flags=today_flags,
    )

    # Strategy Library (Task 9, section 4.10): the library flags REORDER / FILTER / APPEND the
    # engine's already-ranked starter strategies (promoted first, suppressed excluded,
    # cross-context appended), and carry each strategy's library_item_id + "Also worked in
    # [chapter]" tags. This changes the strategy ORDER and the appended cross-context items
    # only; it NEVER touches result.scores / total / tier (those stay section 4.4 exact). The
    # reads are fail-open, so a missing 0014 table leaves the engine's starter order intact.
    high_dimensions = _high_dimensions(result.scores)
    library_inputs = strategy_library.ranking_inputs_for_plan(
        user,
        child_id=child["id"],
        chapter=chapter,
        scenario_type=activity_code,
        high_dimensions=high_dimensions,
    )
    plan_strategies = _apply_library(result.strategies, library_inputs)

    scheduled_pulse_at = compute_scheduled_pulse_at(activity_date, now=now)

    stored = _store_activity_record(
        user,
        child_id=child["id"],
        chapter=chapter,
        activity_code=activity_code,
        activity_date=activity_date,
        today_flags=today_flags,
        context_note=context_note,
        scheduled_pulse_at=scheduled_pulse_at,
        result=result,
        plan_strategies=plan_strategies,
    )

    # Auto-save (section 4.10): persist each starter strategy as a strategy_library_item for
    # this recipient + scenario, idempotent on a re-plan. Non-interrupting (the plan is already
    # stored), so a library write failure never fails the plan. Runs AFTER the store so the plan
    # is durable first.
    strategy_library.auto_save_plan_strategies(
        user,
        child_id=child["id"],
        chapter=chapter,
        scenario_type=activity_code,
        strategies=[s.model_dump() for s in plan_strategies],
        high_dimensions=high_dimensions,
    )

    return _to_plan(stored, result, chapter, activity_code, scheduled_pulse_at, plan_strategies)


def compute_scheduled_pulse_at(
    activity_date: Optional[date_type], *, now: Optional[datetime] = None
) -> datetime:
    """The section 4.4 step 9 Pulse time: activity date + 2h, else 09:00 next day.

    With an activity date, the Pulse is due that date at the default time plus the
    delay (the activity date does not carry a time of day, so the default time is
    the anchor and the delay is added). With no date, it is due at the default time
    on the day after `now`. Returns a naive-or-aware datetime mirroring `now`'s
    tzinfo; the column is timestamptz.
    """
    base_now = now if now is not None else datetime.now()
    if activity_date is not None:
        anchor = datetime.combine(activity_date, PULSE_DEFAULT_TIME, tzinfo=base_now.tzinfo)
        return anchor + timedelta(hours=PULSE_DELAY_HOURS)
    next_day = (base_now + timedelta(days=1)).date()
    return datetime.combine(next_day, PULSE_DEFAULT_TIME, tzinfo=base_now.tzinfo)


def list_chapter_activities(chapter: str) -> List[ActivityOption]:
    """The seeded scenarios for a chapter, as activity-picker options.

    Reads the seed (global reference data, the same for every user), so it needs no
    user scoping. Returns each scenario's code, name, and base tier in the seed's
    order. An unknown chapter yields an empty list (the route validates the chapter
    code separately).
    """
    tables = load_seed()
    options = [
        ActivityOption(
            activity_code=row.activity_code,
            activity_name=row.activity_name,
            tier=row.tier,
        )
        for row in tables.scenarios
        if row.chapter == chapter
    ]
    return options


# ---------------------------------------------------------------------------
# reads (GET /api/v1/plans + GET /api/v1/plans/{activity_id})
# ---------------------------------------------------------------------------


def list_stored_plans(
    user: AuthedUser, *, chapter: Optional[str] = None, now: Optional[datetime] = None
) -> List[PlanSummary]:
    """The caller's stored plans as lightweight summaries, newest first.

    Reads the caller's activity_record rows (RLS-scoped, so only their own), optionally
    filtered to one chapter, ordered by created_at descending (newest first). Each row
    becomes a PlanSummary carrying the STORED identity + score (no re-run of the
    engine) plus the pulse status: an activity is pulse_exists once any pulse_record
    exists for it, and pulse_due when its scheduled_pulse_at has passed with no pulse
    yet (the section 4.7 pending definition). The pulsed-activity ids are read once for
    the whole list. now is injectable for tests (the due comparison); it defaults to
    UTC now.
    """
    base_now = _utc_now(now)
    client = get_anon_client(user.access_token)

    query = (
        client.table(ACTIVITY_RECORD_TABLE)
        .select("id, chapter, activity_name, tier, total, scheduled_pulse_at, created_at")
        .eq("user_id", user.id)
    )
    if chapter is not None:
        query = query.eq("chapter", chapter)
    rows = _rows(query.order("created_at", desc=True).execute())

    pulsed_ids = _pulsed_activity_ids(user)

    summaries: List[PlanSummary] = []
    for row in rows:
        activity_id = row.get("id")
        if activity_id is None:
            continue
        pulse_exists = str(activity_id) in pulsed_ids
        summaries.append(
            PlanSummary(
                activity_id=str(activity_id),
                chapter=row.get("chapter"),
                activity_name=row.get("activity_name") or "",
                tier=Tier(row.get("tier")),
                total=row.get("total"),
                created_at=_parse_dt(row.get("created_at")) or base_now,
                pulse_exists=pulse_exists,
                pulse_due=_is_pulse_due(row, pulse_exists, base_now),
            )
        )

    # PostgREST already ordered newest-first; re-sort defensively (a fake client or a
    # null created_at must not reorder the list) so the contract holds regardless.
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


def get_stored_plan(user: AuthedUser, activity_id: str) -> PreparationPlan:
    """The caller's full stored plan for one activity, in the PreparationPlan shape.

    Reads the one activity_record by id under RLS (a forged id for another user matches
    nothing => PlanNotFoundError, the route's 404, without confirming existence). Shapes
    the STORED columns back into PreparationPlan: the final scores, total, tier, the
    stored JSON strategies, and the scheduled pulse time. It NEVER re-runs the engine,
    so dimension_explanations (a step 10 derivation, not stored) is null and
    used_chapter_average stays at its default (it is a POST-time estimate flag, not a
    stored value).
    """
    row = _get_owned_activity_full(user, activity_id)
    if row is None:
        raise PlanNotFoundError("No such plan for this user")
    return _stored_row_to_plan(row)


def _is_pulse_due(row: Dict[str, Any], pulse_exists: bool, now: datetime) -> bool:
    """True when the activity's scheduled Pulse has passed with no pulse yet (4.7).

    The section 4.7 "pending" condition: scheduled_pulse_at is at or before now AND no
    pulse_record exists for the activity. A plan whose pulse time is still in the future,
    or that has already been pulsed, is not due.
    """
    if pulse_exists:
        return False
    scheduled_at = _parse_dt(row.get("scheduled_pulse_at"))
    if scheduled_at is None:
        return False
    return scheduled_at <= now


def _pulsed_activity_ids(user: AuthedUser) -> Set[str]:
    """The set of the caller's activity ids that already have a pulse (completed/skipped).

    The same source the pending list uses (a pulse_record exists for the activity), read
    once so a list of N plans does not issue N pulse lookups. RLS scopes it to the
    caller's pulses.
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE).select("activity_id").eq("user_id", user.id).execute()
    )
    return {str(r.get("activity_id")) for r in rows if r.get("activity_id") is not None}


def _get_owned_activity_full(user: AuthedUser, activity_id: str) -> Optional[Dict[str, Any]]:
    """The caller's full activity_record by id, or None if it is not theirs.

    Selects every stored plan column the PreparationPlan reconstruction needs. RLS scopes
    the read to the caller, so a forged id for another user returns nothing (404 at the
    route), never another user's row.
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(ACTIVITY_RECORD_TABLE)
        .select(
            "id, chapter, activity_code, activity_name, "
            "temporal, sensory, logistical, human, total, tier, "
            "strategies, scheduled_pulse_at"
        )
        .eq("id", activity_id)
        .eq("user_id", user.id)
        .execute()
    )


def _stored_row_to_plan(row: Dict[str, Any]) -> PreparationPlan:
    """Shape a stored activity_record row into the PreparationPlan the app renders.

    Reads the STORED values only (no engine run): the final four scores, the total and
    tier, and the stored JSON strategies (each {title, detail, also_worked_in_chapter}).
    dimension_explanations is null (not stored) and used_chapter_average stays at its
    default (a POST-time flag, not persisted).
    """
    return PreparationPlan(
        activity_id=str(row.get("id")),
        chapter=row.get("chapter"),
        activity_code=row.get("activity_code"),
        activity_name=row.get("activity_name") or "",
        scores=DimensionScores(
            temporal=row.get("temporal"),
            sensory=row.get("sensory"),
            logistical=row.get("logistical"),
            human=row.get("human"),
        ),
        total=row.get("total"),
        tier=Tier(row.get("tier")),
        strategies=_strategies_from_stored(row.get("strategies")),
        dimension_explanations=None,
        scheduled_pulse_at=_parse_dt(row.get("scheduled_pulse_at")),
    )


def _strategies_from_stored(stored: Any) -> List[PlanStrategy]:
    """The stored strategies JSON back into the ranked PlanStrategy list (order kept).

    The activity_record stores strategies as an ordered array of
    {title, detail, also_worked_in_chapter}; map each back to a PlanStrategy, keeping the
    stored order (the rank the plan was returned in). A null/empty value yields an empty
    list.
    """
    if not isinstance(stored, list):
        return []
    strategies: List[PlanStrategy] = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        strategies.append(
            PlanStrategy(
                title=item.get("title") or "",
                detail=item.get("detail") or "",
                also_worked_in_chapter=item.get("also_worked_in_chapter"),
            )
        )
    return strategies


def _utc_now(now: Optional[datetime]) -> datetime:
    if now is not None:
        return now
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a timestamptz value (ISO string or datetime) to an aware datetime.

    Mirrors the parser in app/services/pulse.py: a datetime passes through (assumed UTC
    if naive), an ISO string (with a trailing Z normalised) is parsed, anything else is
    None.
    """
    return parse_timestamptz(value)


# ---------------------------------------------------------------------------
# the Strategy Library overlay (Task 9, section 4.10): reorder / filter / append
# ---------------------------------------------------------------------------


def _high_dimensions(scores: Dict[Dimension, int]) -> List[str]:
    """The dimension codes scoring at or above the section 4.4 step 7 high cut (>= 3).

    The cross-context test matches a saved strategy's dimensions against THIS activity's
    high-scoring dimensions; this returns those dimension codes (temporal/sensory/...). Reads
    the named HIGH_DIMENSION_SCORE bound, never the literal (the SeedData.md hard rule).
    """
    return [dim.value for dim, score in scores.items() if score >= HIGH_DIMENSION_SCORE]


def _apply_library(
    engine_strategies: List[Any],
    inputs: "strategy_library.StrategyLibraryInputs",
) -> List[PlanStrategy]:
    """Overlay the section 4.10 library flags onto the engine's ranked starter strategies.

    The library REORDERS / FILTERS / APPENDS only (it never changes a score): promoted titles
    float to the front (keeping their relative order), suppressed titles are dropped, each
    surviving starter carries its library_item_id (so the app can remove it), and the
    cross-context matches are appended last with their "Also worked in [chapter]" tag. The
    engine already produced the dimension-matched starter order; this is the section 4.4 step 7
    promotion / suppression / cross-context layer the engine left as the Task 9 hook. When the
    library has no inputs (a fresh recipient or the 0014 table not applied), the engine's
    starter order is returned unchanged.
    """
    promoted = set(inputs.promoted_titles)
    suppressed = set(inputs.suppressed_titles)

    surviving = [s for s in engine_strategies if s.title not in suppressed]
    promoted_first = [s for s in surviving if s.title in promoted]
    remaining = [s for s in surviving if s.title not in promoted]
    ordered = promoted_first + remaining

    plan_strategies = [
        PlanStrategy(
            title=s.title,
            detail=s.body,
            library_item_id=inputs.item_id_by_title.get(s.title),
            also_worked_in_chapter=s.cross_context_chapter,
        )
        for s in ordered
    ]

    # Append the cross-context strategies, each labelled "Also worked in [chapter]" (section
    # 4.10). They carry both the richer also_worked_in tag and the scalar source code, plus the
    # saved item id so the app can dismiss the surfacing per chapter.
    for cc in inputs.cross_context:
        plan_strategies.append(
            PlanStrategy(
                title=cc.title,
                detail=cc.body,
                library_item_id=cc.library_item_id,
                also_worked_in=[
                    AlsoWorkedIn(
                        chapter=cc.source_chapter,
                        label=strategy_library.cross_context_label(cc.source_chapter),
                    )
                ],
                also_worked_in_chapter=cc.source_chapter,
            )
        )
    return plan_strategies


# ---------------------------------------------------------------------------
# persistence (step 8)
# ---------------------------------------------------------------------------


def _store_activity_record(
    user: AuthedUser,
    *,
    child_id: str,
    chapter: str,
    activity_code: str,
    activity_date: Optional[date_type],
    today_flags: List[str],
    context_note: Optional[str],
    scheduled_pulse_at: datetime,
    result: EngineResult,
    plan_strategies: List[PlanStrategy],
) -> Dict[str, Any]:
    """Insert the activity_record and return the stored row (write confirmed).

    user_id is set from the session and child_id from the user's own recipient
    (never from the client); the RLS insert policy additionally requires
    user_id == auth.uid(). If the insert returns no representation, the row is
    read back under RLS so the plan is only ever returned for a row that exists
    (section 4.4 step 8: confirm the write before returning).

    plan_strategies is the library-adjusted ranked list (promoted first, suppressed
    excluded, cross-context appended); the stored strategies JSON is this list, so a
    stored-plan re-read returns the same order the POST returned (the library item ids are
    a live concern and are NOT stored, the app re-fetches them on the live plan).
    """
    client = get_anon_client(user.access_token)
    insert_row = {
        "user_id": user.id,
        "child_id": child_id,
        "chapter": chapter,
        "activity_code": activity_code,
        "activity_name": result.activity_name,
        "activity_date": activity_date.isoformat() if activity_date else None,
        "base_temporal": result.base_scores[Dimension.TEMPORAL],
        "base_sensory": result.base_scores[Dimension.SENSORY],
        "base_logistical": result.base_scores[Dimension.LOGISTICAL],
        "base_human": result.base_scores[Dimension.HUMAN],
        "temporal": result.scores[Dimension.TEMPORAL],
        "sensory": result.scores[Dimension.SENSORY],
        "logistical": result.scores[Dimension.LOGISTICAL],
        "human": result.scores[Dimension.HUMAN],
        "total": result.total,
        "tier": result.tier.value,
        "today_flags": list(today_flags),
        "strategies": _strategies_json(plan_strategies),
        "context_note": context_note,
        "scheduled_pulse_at": scheduled_pulse_at.isoformat(),
    }
    created = _first(client.table(ACTIVITY_RECORD_TABLE).insert(insert_row).execute())
    if created is not None:
        return created
    # No representation returned: read back the just-inserted row under RLS so the
    # write is confirmed before the plan is returned.
    confirmed = _first(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("scheduled_pulse_at", scheduled_pulse_at.isoformat())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if confirmed is None:
        raise RuntimeError("activity_record write could not be confirmed")
    return confirmed


def _strategies_json(plan_strategies: List[PlanStrategy]) -> List[Dict[str, Any]]:
    """The library-adjusted ranked strategies as the stored JSON array.

    Stores the title, detail, and the single also_worked_in_chapter source code (the
    activity_record's stored shape, {title, detail, also_worked_in_chapter}); library_item_id
    and the richer also_worked_in list are LIVE concerns the app re-fetches on the live plan,
    not persisted (a stored re-read returns the order without the live remove ids).
    """
    return [
        {
            "title": s.title,
            "detail": s.detail,
            "also_worked_in_chapter": s.also_worked_in_chapter,
        }
        for s in plan_strategies
    ]


# ---------------------------------------------------------------------------
# shaping (step 10)
# ---------------------------------------------------------------------------


def _to_plan(
    stored: Dict[str, Any],
    result: EngineResult,
    chapter: str,
    activity_code: str,
    scheduled_pulse_at: datetime,
    plan_strategies: List[PlanStrategy],
) -> PreparationPlan:
    """Shape the stored row + engine result into the PreparationPlan the app renders.

    plan_strategies is the library-adjusted ranked list (built once in prepare_plan and
    stored), so the returned plan, the stored JSON, and the auto-save all see the same list.
    """
    return PreparationPlan(
        activity_id=str(stored.get("id")),
        chapter=chapter,
        activity_code=activity_code,
        activity_name=result.activity_name,
        scores=DimensionScores(
            temporal=result.scores[Dimension.TEMPORAL],
            sensory=result.scores[Dimension.SENSORY],
            logistical=result.scores[Dimension.LOGISTICAL],
            human=result.scores[Dimension.HUMAN],
        ),
        total=result.total,
        tier=Tier(result.tier),
        strategies=plan_strategies,
        dimension_explanations=DimensionExplanations(
            temporal=result.dimension_explanations[Dimension.TEMPORAL.value],
            sensory=result.dimension_explanations[Dimension.SENSORY.value],
            logistical=result.dimension_explanations[Dimension.LOGISTICAL.value],
            human=result.dimension_explanations[Dimension.HUMAN.value],
        ),
        scheduled_pulse_at=scheduled_pulse_at,
        used_chapter_average=result.used_chapter_average,
    )
