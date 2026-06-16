"""LastOutcome pydantic schema (v3): "What helped last time" (ProductReview.md item 5).

The cross-repo contract for the prepare-time recall read (GET /api/v1/chapters/{chapter}
/last-outcome, HardRules/Api/Modules/Engine.md, HardRules/App/Modules/Plan.md). When a
Coordinator opens the prepare flow for a chapter (and optionally the check-in), the app
surfaces a calm, FACTUAL recall of the family's OWN prior outcome in that chapter. This is
a READ of stored facts, never a prediction and never a new score: every field is read back
from the recipient's own pulse_record + activity_record + strategy_library_item rows.

  - LastOutcome: the most recent prior outcome in the chapter (a completed, non-skipped
    pulse) plus which saved strategy has worked (a §4.10 PROMOTED strategy for the
    recipient + chapter, if any). The app renders the facts as plain language ("Last time,
    [strategy] helped", "[dimension] was the biggest pressure"); it authors no claim it
    cannot ground in this object.

The endpoint returns LastOutcome OR null. null means there is no prior completed outcome
in the chapter (a first-time chapter, or a history of only skipped pulses): the app shows
nothing. The app reads what the api returns and recomputes nothing (the render-the-engine
rule); the api does NO scoring here (the §4.8 / §4.10 reads are of values already stored).

The outcome and tier vocabulary are the engine's enums (Outcome, Tier) so there is one
definition of those codes across the LCE / LCI / Pulse / this recall read; the dimension
vocabulary is the engine's Dimension enum.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.engines.lci import Outcome
from app.models.chapters import Chapter
from app.models.seed import Dimension, Tier


class LastOutcome(BaseModel):
    """The family's OWN most recent prior outcome in a chapter (ProductReview.md item 5).

    A read of stored facts for "What helped last time", surfaced calmly at prepare-time.
    All fields come from the recipient's own stored rows (RLS-scoped); nothing here is a
    score the api computed for this read, and nothing is a prediction.

    Fields:
      chapter             the Life Chapter this recall is for (the stable code).
      activity_name       the activity of the most recent prior completed pulse (the human
                          label the app names: "Last time at [activity]...").
      outcome_code        that pulse's two-tap outcome (well / okay / difficult). NEVER
                          skipped: a skipped pulse is not an outcome to recall, so the read
                          finds the most recent NON-skipped pulse (and returns null if every
                          pulse in the chapter was skipped).
      tier_recommended    the participation tier that plan used (Full / Modified / Pivot),
                          the stored value the pulse copied (never re-derived). Lets the app
                          state "the Continuity Pivot worked here" only when grounded.
      challenge_dimension the biggest-pressure dimension the Coordinator named on that pulse
                          (the second question), or null when they did not pick one. The
                          app renders "[dimension] was the biggest pressure last time".
      worked_strategy     the title of a strategy that has WORKED for this recipient +
                          chapter: a §4.10 PROMOTED strategy (positive outcomes >= 2 AND more
                          positives than negatives), the most-positive one. Null when nothing
                          has crossed the promotion bar yet (no overclaim from a single use).
                          Read from the saved strategy_library_item counts, not computed here.
      pivot_helped        true ONLY when the most recent prior outcome was a POSITIVE one
                          (the §4.8 sense: Well/Okay under any tier, OR Difficult under Pivot,
                          which §4.8 scores positively because the plan protected the family)
                          recorded under the Continuity Pivot tier. It is the grounded fact
                          behind "the Continuity Pivot worked better than Full Engagement"; it
                          is a stored-fact flag, never a prediction. False otherwise.
      recorded_at         when that prior outcome was recorded (the pulse timestamp), so the
                          app can phrase recency if it chooses; not PII.
    """

    model_config = ConfigDict(use_enum_values=True)

    chapter: Chapter
    activity_name: str
    outcome_code: Outcome
    tier_recommended: Tier
    challenge_dimension: Optional[Dimension] = None
    worked_strategy: Optional[str] = None
    pivot_helped: bool = False
    recorded_at: datetime = Field(...)
