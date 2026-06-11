"""Pulse pydantic schemas (v3): the post-activity check-in request + response.

The cross-repo contract for the Pulse endpoints (Product.md section 4.7,
HardRules/Api/Modules/Pulse.md, HardRules/App/Modules/Continuity.md). The app
mirrors these shapes; the api is the authoritative schema the app reconciles to.

  - PulseSubmission: the POST /api/v3/pulses body. The app posts
    {activity_id, outcome_code} (its api client maps the chosen outcome to
    outcome_code); challenge_dimension is the optional "main challenge" the second
    question captures (the PRD asks both questions, the api stores the dimension
    when sent and null otherwise). The activity is identified by its stored
    activity_record id; the chapter and the recommended tier are read FROM that
    record server-side, never sent by the client (the structured-data + stored-tier
    rules).
  - PulseRecord: the stored pulse as returned. Field-for-field the app's PulseRecord
    (id, activity_id, outcome_code, challenge_dimension, chapter, timestamp), so the
    app renders it without remapping.
  - PendingPulse: one entry of GET /api/v3/pulses/pending, an activity whose
    scheduled Pulse time has passed with no pulse yet (the in-app prompt source).

The outcome vocabulary is the LCI engine's Outcome enum so there is one definition
of the outcome codes across the Pulse and the index; the dimension vocabulary is
the engine's Dimension enum.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.engines.lci import Outcome
from app.models.chapters_v3 import Chapter
from app.models.seed import Dimension, Tier


class PulseSubmission(BaseModel):
    """The POST /api/v3/pulses body: record the outcome of a prepared activity.

    activity_id is the stored activity_record this Pulse is for; the chapter and the
    recommended tier the LCI adjustment keys on are read from that record, not sent.
    outcome_code is the two-tap outcome (well / okay / difficult, or skipped after a
    Pulse is dismissed twice). challenge_dimension is the optional "main challenge"
    dimension (the second question); it is stored but never feeds the score (only the
    outcome x the stored tier does). A skipped pulse is recorded with a 0 adjustment.
    """

    model_config = ConfigDict(use_enum_values=True)

    activity_id: str = Field(..., min_length=1)
    outcome_code: Outcome
    challenge_dimension: Optional[Dimension] = None


class PulseRecord(BaseModel):
    """A stored pulse as returned to the app (Product.md section 4.7).

    Mirrors tiwani-app's PulseRecord field-for-field so the app renders it directly:
    id, activity_id, outcome_code, challenge_dimension (null when the Coordinator did
    not pick one), chapter (the stored chapter the Pulse belongs to), and timestamp
    (the ISO instant the pulse was recorded). tier_recommended is carried too (the
    stored tier the adjustment used) so the app can show what the score moved
    against; it is additive to the app's mirror.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str
    activity_id: str
    outcome_code: Outcome
    challenge_dimension: Optional[Dimension] = None
    tier_recommended: Tier
    chapter: Chapter
    timestamp: datetime


class PendingPulse(BaseModel):
    """One pending Pulse: an activity whose scheduled Pulse time has passed unanswered.

    The in-app prompt source (GET /api/v3/pulses/pending): the app shows a check-in
    card for each. activity_id + activity_name + chapter identify it; scheduled_at is
    when the Pulse became due (activity date + 2h, or 09:00 the next day). The app
    owns the persist-across-opens and dismiss-twice behaviour; the api only reports
    what is still pending (no completed or skipped pulse exists for the activity).
    """

    model_config = ConfigDict(use_enum_values=True)

    activity_id: str
    activity_name: str
    chapter: Chapter
    scheduled_at: datetime
