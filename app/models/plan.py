"""Preparation Plan pydantic schemas (v3): the LCE request + response contracts.

The cross-repo contract for the engine endpoints (Product.md section 4.4 / 4.5,
HardRules/Api/Modules/Engine.md, HardRules/App/Modules/Plan.md). The app mirrors
these shapes EXACTLY and renders the output; it never recomputes a score (the
LCE is server-side only). Do not change a field name or type here without changing
the app's mirror.

  - PreparePlanRequest: what the app posts to POST /api/v1/plans. The activity is
    a (chapter, activity_code) pair; today_flags is the section 4.4 "today" flags
    as TG- codes. The app sends the flags; it NEVER applies the +1/+2 itself.
  - PreparationPlan: what the engine returns (the section 4.4 output + the stored
    activity id + the scheduled Pulse time the app shows). The SAME shape is returned
    by GET /api/v1/plans/{activity_id} reading the STORED activity_record back (no
    re-run of the engine); dimension_explanations is optional because it is not stored
    (it is null on a stored-plan read, populated on the POST that just ran the engine).
  - PlanSummary: one row of GET /api/v1/plans (the caller's stored plans, newest
    first): the lightweight identity + score + the pulse status, so the app can list
    "your prepared plans" without fetching each full plan.
  - PlanSummaryPage: the PAGINATED GET /api/v1/plans response (a capped page of
    PlanSummary rows + the keyset cursor), so the list never reads every stored plan
    (prepared plans accumulate per user over time; the /cards precedent).
  - ActivityOption: one row of the activity picker (GET /api/v1/chapters/{chapter}
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


class AlsoWorkedIn(BaseModel):
    """One "Also worked in [chapter]" tag on a cross-context strategy (section 4.10).

    chapter is the source chapter code (the chapter the strategy succeeded in); label is
    the ready-to-render "Also worked in [display name]" text. A cross-context strategy
    carries one entry (the chapter it was promoted from); the list shape lets the app render
    several labels if a strategy ever surfaces from more than one source chapter.
    """

    model_config = ConfigDict(frozen=True)

    chapter: str
    label: str


class PlanStrategy(BaseModel):
    """One strategy in the plan's ranked list (section 4.4 step 7 + Fusion Layer output).

    title + detail are the strategy text (the seeded source carries flat phrases, so
    title and detail may be the same line; a situated strategy's detail is its
    governed situated sentence).

    Provenance (LCEEngineAddendum.md section 3): every strategy carries where it came
    from, so the Specificity Gate can tell a genuinely personalised Plan from generic
    scenario content, and the app can group and label situated strategies:
      - source: "scenario_base" | "dimension_transfer" | "situated_fusion".
      - derived_from: the active profile tag code(s) that produced it (empty for
        scenario_base and dimension_transfer; the loading tags for situated_fusion).
      - moment: the scenario moment id a situated strategy is attached to (required for
        situated_fusion; null otherwise).
      - moment_label: the user-readable moment name for the app (e.g. "First assembly");
        null unless situated_fusion.

    Strategy Library fields (Task 9, Product.md section 4.10):
      - library_item_id: the saved strategy_library_item id for THIS recipient + scenario,
        so the app can drive the remove action (swipe-to-remove -> suppress after 3) and the
        re-allow. Null when the library has not saved it yet (e.g. the 0014 table is not
        applied), in which case the app simply omits the remove control.
      - also_worked_in: the cross-context "Also worked in [chapter]" tags for a strategy
        surfaced from another chapter; empty for a starter strategy of this scenario.
      - also_worked_in_chapter: the single source-chapter code, kept for the lighter mirror
        and the stored-plan read (the activity_record stores this scalar); null for a starter
        strategy. also_worked_in is the richer Task 9 field; this stays for back-compat.
    """

    title: str
    detail: str
    source: str = "scenario_base"
    derived_from: List[str] = Field(default_factory=list)
    moment: Optional[str] = None
    moment_label: Optional[str] = None
    library_item_id: Optional[str] = None
    also_worked_in: List[AlsoWorkedIn] = Field(default_factory=list)
    also_worked_in_chapter: Optional[str] = None


class DimensionExplanations(BaseModel):
    """One plain-English, non-clinical sentence per dimension (section 4.4 step 10)."""

    model_config = ConfigDict(frozen=True)

    temporal: str
    sensory: str
    logistical: str
    human: str


class Specificity(BaseModel):
    """The Specificity Gate result on a Plan (LCEEngineAddendum.md section 4).

    profile_derived is the count of strategies whose derived_from is non-empty;
    situated is the count of situated_fusion strategies. complete is true only when a
    Plan is specific enough to present as a finished Plan (profile_derived >= 2 AND
    situated >= 1); otherwise the engine asks one enrichment question instead of
    shipping a generic Plan. The app can use these to show a subtle specificity signal.
    """

    model_config = ConfigDict(frozen=True)

    profile_derived: int
    situated: int
    complete: bool


class EnrichmentOption(BaseModel):
    """One tap option for the enrichment question: a tag code + its human label."""

    model_config = ConfigDict(frozen=True)

    code: str
    label: str


class Enrichment(BaseModel):
    """The one value-first enrichment question (LCEEngineAddendum.md section 5).

    Present on a PreparationPlan ONLY when the gate did not pass and an enrichment has
    not yet been tried: it improves the Plan now (it is not data collection). question
    is the governed, non-clinical prompt; dimension is the highest-loading pressure
    dimension with no confirming profile tag; options are the tags the carer can tap
    to confirm it (the app re-calls POST /plans with the chosen codes as
    enrichment_answer). Null once the Plan is complete or an enrichment is exhausted.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    dimension: str
    options: List[EnrichmentOption]


class PreparePlanRequest(BaseModel):
    """The POST /api/v1/plans body: prepare an activity and get its plan.

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
    # The enrichment loop (LCEEngineAddendum.md section 5, step 13): the permanent
    # profile tag code(s) the carer tapped in answer to an enrichment question. When
    # present the engine PERSISTS them as the recipient's permanent tags (carer-owned,
    # the byproduct-input model) and re-runs scoring + fusion + the gate in the SAME
    # call. These are PERMANENT profile tags (SN-/TR-/CM-/RC-), never TG- day flags (a
    # TG- code here is a 422); empty on a normal prepare.
    enrichment_answer: List[Tag] = Field(default_factory=list)


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
    (it is a section 4.4 step 10 derivation, not a stored value): POST /api/v1/plans
    populates it from the just-run engine, but GET /api/v1/plans/{activity_id} reads
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
    # The Fusion Layer + Specificity Gate + enrichment (LCEEngineAddendum.md 4-6):
    #   specificity   the gate result (profile_derived, situated, complete). NULL when the
    #                 FUSION_ENABLED server flag is OFF (app/engines/lce/flag.py): the
    #                 Fusion output is gated on the psychiatrist copy sign-off (G2), so an
    #                 OFF plan is exactly pre-fusion and omits the gate.
    #   enrichment    the one value-first question, present ONLY when not complete and
    #                 no enrichment has been tried yet; null otherwise (and always null
    #                 while the flag is OFF).
    #   getting_to_know  true when the Plan is still not complete AFTER one enrichment:
    #                    the app shows the calm "Still getting to know [child]" state
    #                    over the best available Plan (always false while the flag is OFF).
    specificity: Optional[Specificity] = None
    enrichment: Optional[Enrichment] = None
    getting_to_know: bool = False


class PlanSummary(BaseModel):
    """One stored plan in the caller's list (GET /api/v1/plans), newest first.

    A lightweight projection of an activity_record so the app can show "your prepared
    plans" without fetching each full plan: the identity (activity_id, chapter,
    activity_name), the headline score (tier + total, the STORED values), and when it
    was prepared (created_at). The pulse status is derived the same way the pending
    list is (section 4.7): pulse_exists is true once any pulse_record (completed or
    skipped) exists for the activity; pulse_due is true when the scheduled Pulse time
    has passed AND no pulse exists yet (the activity is currently awaiting a check-in).
    A plan with no pulse and a future scheduled time has both false. The full plan is
    at GET /api/v1/plans/{activity_id}.
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


class PlanSummaryPage(BaseModel):
    """One PAGE of the caller's stored plans (GET /api/v1/plans), newest first.

    The list endpoint is paginated so it never reads every plan the Coordinator has ever
    prepared (prepared plans accumulate per user over time): each request returns at most a
    capped number of rows (the api clamps a larger ?limit), newest first, plus the signal
    for whether more exist:
      plans        the page of PlanSummary rows, newest first (RLS-scoped to the caller).
      next_cursor  the keyset cursor to pass back as ?before to fetch the NEXT (older) page,
                   or null when this is the last page. It is the created_at of the last row
                   on a FULL page (a page shorter than the limit has no more, so next_cursor
                   is null). The app sends it straight back as `before`; it is a timestamp,
                   not PII. A keyset cursor (not an offset) is used because the list is
                   already ordered by created_at descending, so it is stable as new plans
                   are prepared at the top. Mirrors the /cards CardPage precedent.
    """

    plans: List[PlanSummary]
    next_cursor: Optional[datetime] = None


class ActivityOption(BaseModel):
    """One option in the activity picker (GET /api/v1/chapters/{chapter}/activities).

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
