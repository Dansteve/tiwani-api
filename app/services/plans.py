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
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.lce import EngineResult, run_engine
from app.models.plan import (
    ActivityOption,
    DimensionExplanations,
    DimensionScores,
    PlanStrategy,
    PreparationPlan,
)
from app.models.seed import Dimension, Tier
from app.seed import load_seed
from app.services.profile import _first, get_child

ACTIVITY_RECORD_TABLE = "activity_record"

# Section 4.4 step 9 Pulse-scheduling constants. The Pulse is due the activity date
# + this many hours; with no date it is due at the default time the next day. These
# are SCHEDULING parameters (a clock concern), deliberately kept in the service and
# NOT in the engine package, so the engine source stays free of any numeric literal
# (the SeedData.md hard rule / the pytest guard over app/engines/lce).
PULSE_DELAY_HOURS = 2
PULSE_DEFAULT_TIME = time(hour=9, minute=0)


class NoCareRecipientError(Exception):
    """Raised when the user has no care recipient to plan for (route maps to 409)."""


def prepare_plan(
    user: AuthedUser,
    *,
    chapter: str,
    activity_code: str,
    today_flags: List[str],
    activity_date: Optional[date_type] = None,
    context_note: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PreparationPlan:
    """Run the engine for the user's care recipient, store the record, return the plan.

    Steps, in order (section 4.4):
      0. fetch the user's care recipient (the SL code + permanent tags the engine
         scores from). No recipient => NoCareRecipientError (the app must onboard).
      1 to 7 + 10. run_engine (pure, seeded rows).
      9. compute scheduled_pulse_at (activity date + 2h, or 09:00 next day).
      8. INSERT the activity_record and CONFIRM the write (re-read if the insert
         returns no representation), so the plan is never returned for an unsaved
         record.
      10. shape and return the PreparationPlan.

    now is injectable for tests (the schedule's "next day" base); it defaults to
    the current time and is the ONLY clock the flow uses (the scoring never reads a
    clock).
    """
    child = get_child(user)
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
    )

    return _to_plan(stored, result, chapter, activity_code, scheduled_pulse_at)


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
) -> Dict[str, Any]:
    """Insert the activity_record and return the stored row (write confirmed).

    user_id is set from the session and child_id from the user's own recipient
    (never from the client); the RLS insert policy additionally requires
    user_id == auth.uid(). If the insert returns no representation, the row is
    read back under RLS so the plan is only ever returned for a row that exists
    (section 4.4 step 8: confirm the write before returning).
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
        "strategies": _strategies_json(result),
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


def _strategies_json(result: EngineResult) -> List[Dict[str, Any]]:
    """The ranked strategies as the stored/returned JSON array."""
    return [
        {
            "title": s.title,
            "detail": s.body,
            "also_worked_in_chapter": s.cross_context_chapter,
        }
        for s in result.strategies
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
) -> PreparationPlan:
    """Shape the stored row + engine result into the PreparationPlan the app renders."""
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
        strategies=[
            PlanStrategy(
                title=s.title,
                detail=s.body,
                also_worked_in_chapter=s.cross_context_chapter,
            )
            for s in result.strategies
        ],
        dimension_explanations=DimensionExplanations(
            temporal=result.dimension_explanations[Dimension.TEMPORAL.value],
            sensory=result.dimension_explanations[Dimension.SENSORY.value],
            logistical=result.dimension_explanations[Dimension.LOGISTICAL.value],
            human=result.dimension_explanations[Dimension.HUMAN.value],
        ),
        scheduled_pulse_at=scheduled_pulse_at,
        used_chapter_average=result.used_chapter_average,
    )
