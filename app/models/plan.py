"""Preparation Plan pydantic schemas (v3): the LCE request + response contracts.

The cross-repo contract for the engine endpoints (Product.md section 4.4 / 4.5,
HardRules/Api/Modules/Engine.md, HardRules/App/Modules/Plan.md). The app mirrors
these shapes EXACTLY and renders the output; it never recomputes a score (the
LCE is server-side only). Do not change a field name or type here without changing
the app's mirror.

  - PreparePlanRequest: what the app posts to POST /api/v3/plans. The activity is
    a (chapter, activity_code) pair; today_flags is the section 4.4 "today" flags
    as TG- codes. The app sends the flags; it NEVER applies the +1/+2 itself.
  - PreparationPlan: what the engine returns (the section 4.4 output + the stored
    activity id + the scheduled Pulse time the app shows). The SAME shape is returned
    by GET /api/v3/plans/{activity_id} reading the STORED activity_record back (no
    re-run of the engine); dimension_explanations is optional because it is not stored
    (it is null on a stored-plan read, populated on the POST that just ran the engine).
  - PlanSummary: one row of GET /api/v3/plans (the caller's stored plans, newest
    first): the lightweight identity + score + the pulse status, so the app can list
    "your prepared plans" without fetching each full plan.
  - ActivityOption: one row of the activity picker (GET /api/v3/chapters/{chapter}
    /activities): a scenario's code, name, and base tier for the app's list.

The four pressure dimensions and the tier are the engine's (Product.md section
4.4); DimensionScores and the tier values come from app/models/seed.py so there is
one definition of the score shape and the tier vocabulary.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.child_profile import Tag
from app.models.seed import Tier


class DimensionScores(BaseModel):
    """The four pressure-dimension scores, each a whole number 1 to 5.

    The same shape for the engine's final scores and (on the activity_record) the
    base scores. Keyed by the four dimension names the app renders.
    """

    model_config = ConfigDict(frozen=True)

    temporal: int = Field(..., ge=1, le=5)
    sensory: int = Field(..., ge=1, le=5)
    logistical: int = Field(..., ge=1, le=5)
    human: int = Field(..., ge=1, le=5)


class PlanStrategy(BaseModel):
    """One strategy in the plan's ranked list (section 4.4 step 7 output).

    title + detail are the seeded strategy text (the source carries flat phrases,
    so title and detail may be the same line). also_worked_in_chapter is set only
    for a cross-context strategy appended by the Strategy Library (Task 9), shown
    by the app as "Also worked in [chapter]"; null for a starter strategy.
    """

    title: str
    detail: str
    also_worked_in_chapter: Optional[str] = None


class DimensionExplanations(BaseModel):
    """One plain-English, non-clinical sentence per dimension (section 4.4 step 10)."""

    model_config = ConfigDict(frozen=True)

    temporal: str
    sensory: str
    logistical: str
    human: str


class PreparePlanRequest(BaseModel):
    """The POST /api/v3/plans body: prepare an activity and get its plan.

    chapter + activity_code select the activity from the seeded scenario matrix; a
    code with no scenario row is a custom activity (the engine falls back to the
    chapter average and the plan says so). date is the optional activity date (used
    only to schedule the Pulse, never in the scoring). today_flags are the section
    4.4 "today" flags as TG- tag codes; the app sends them and never applies the
    +1/+2 itself. context_note is optional free text stored on the record and NEVER
    read by the engine.
    """

    chapter: str = Field(..., min_length=1)
    activity_code: str = Field(..., min_length=1)
    date: Optional[date_type] = None
    today_flags: List[Tag] = Field(default_factory=list)
    context_note: Optional[str] = None


class PreparationPlan(BaseModel):
    """The engine's plan for an activity (section 4.4 / 4.5 output the app renders).

    activity_id is the stored activity_record id (the write is confirmed before
    this returns, section 4.4 step 8). scores is the final four-dimension result;
    total (4 to 20) and tier follow from it. strategies is the ranked list;
    dimension_explanations is one non-clinical sentence per dimension.
    scheduled_pulse_at is when the Post-Activity Pulse is scheduled (the activity
    date + 2 hours, or 09:00 the next day if no date), shown by the app.
    used_chapter_average is True for a custom activity, so the app can say the
    scores are an estimate.

    dimension_explanations is OPTIONAL because the activity_record does not store it
    (it is a section 4.4 step 10 derivation, not a stored value): POST /api/v3/plans
    populates it from the just-run engine, but GET /api/v3/plans/{activity_id} reads
    the stored row back and returns it as null (it never re-runs the engine to derive
    it). The app's POST view always receives it; a stored-plan view must allow null.
    """

    model_config = ConfigDict(use_enum_values=True)

    activity_id: str
    chapter: str
    activity_code: str
    activity_name: str
    scores: DimensionScores
    total: int = Field(..., ge=4, le=20)
    tier: Tier
    strategies: List[PlanStrategy]
    dimension_explanations: Optional[DimensionExplanations] = None
    scheduled_pulse_at: datetime
    used_chapter_average: bool = False


class PlanSummary(BaseModel):
    """One stored plan in the caller's list (GET /api/v3/plans), newest first.

    A lightweight projection of an activity_record so the app can show "your prepared
    plans" without fetching each full plan: the identity (activity_id, chapter,
    activity_name), the headline score (tier + total, the STORED values), and when it
    was prepared (created_at). The pulse status is derived the same way the pending
    list is (section 4.7): pulse_exists is true once any pulse_record (completed or
    skipped) exists for the activity; pulse_due is true when the scheduled Pulse time
    has passed AND no pulse exists yet (the activity is currently awaiting a check-in).
    A plan with no pulse and a future scheduled time has both false. The full plan is
    at GET /api/v3/plans/{activity_id}.
    """

    model_config = ConfigDict(use_enum_values=True)

    activity_id: str
    chapter: str
    activity_name: str
    tier: Tier
    total: int = Field(..., ge=4, le=20)
    created_at: datetime
    pulse_exists: bool = False
    pulse_due: bool = False


class ActivityOption(BaseModel):
    """One option in the activity picker (GET /api/v3/chapters/{chapter}/activities).

    A seeded scenario for the chapter: its stable code, human name, and the
    participation tier (the source's tier for the un-adjusted activity), so the app
    can show the picker with a sense of each activity's baseline pressure. The
    engine still recomputes the tier for the actual plan with the child's profile,
    so this `tier` is the BASELINE only, not the plan's tier.

    The field is named `tier` (not `base_tier`) to match the app's already-built
    mirror (`ChapterActivity.tier`, the parallel feat/app-plan work, Task 5 notes):
    one cross-repo contract, the app does not re-key.
    """

    model_config = ConfigDict(use_enum_values=True)

    activity_code: str
    activity_name: str
    tier: Tier
