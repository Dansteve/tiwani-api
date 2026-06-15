"""LCI response schemas (v3): the overall and per-chapter index the dashboard reads.

The cross-repo contract for the LCI read endpoints (Product.md section 4.8,
HardRules/Api/Modules/Index.md, HardRules/App/Modules/Continuity.md). The app
mirrors these; the api is the authoritative schema. The values are computed in
app/engines/lci and never recomputed in the app.

  - ChapterLci: GET /api/v1/lci/chapters returns one per Life Chapter for the user.
    Mirrors tiwani-app's ChapterLci (chapter, score, trajectory, pulse_count,
    timestamp) and ADDS two things the app reconciles to: score is NULLABLE (null
    for a chapter with no pulse, rendered "--", not 0), and `label` carries the
    section 4.8 sparse-data label ("building your picture" for 1 to 2 pulses, "--"
    for none, null at 3+ pulses).
  - OverallLci: GET /api/v1/lci/overall returns the single overall index. Mirrors
    tiwani-app's OverallLciSnapshot (score, trajectory, chapters_included,
    timestamp) and makes score NULLABLE (null until any chapter has a pulse) plus
    the same `label`.
  - LciHistory / LciSeries / LciHistoryPoint: GET /api/v1/lci/history returns the
    DISCRETE recorded LCI points the "Your check-in history" view renders (the
    de-risked "timeline", the researcher's build-with-conditions verdict). A read of
    the stored lci_snapshot rows, NOT a new engine: each real check-in instant is a
    point carrying its api-owned section 4.3 band (a zone, never a precise altitude),
    plus the honesty signals the app cannot lie without (reading_count for the
    three-reading floor, latest_taken_at + is_stale for stale-stops).

Trajectory is the engine's Trajectory enum (the app's strengthening / holding_steady
/ under_pressure / building_picture codes, no remap). The band is the engine's LciBand
enum (the app's none / stable / pressure / critical codes). Chapter codes are the
Chapter enum.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from app.engines.lci import LciBand, Trajectory
from app.models.chapters import Chapter

# The score bounds the schema validates (section 4.8: 0 to 100). A null score means
# "no pulse yet" (the chapter or overall is rendered "--"); a present score is a
# whole number in this range.
_MIN_LCI = 0
_MAX_LCI = 100


class ChapterLci(BaseModel):
    """One chapter's Life Continuity Index for the current user (section 4.8).

    score is the chapter's current 0 to 100 index, or null for a chapter with no
    pulse (excluded from the overall average, rendered "--"). trajectory is the
    weekly band vs the score 7 days prior (building_picture when there is no prior
    point). pulse_count is how many pulses the chapter has (drives the sparse label).
    label is the section 4.8 sparse-data label: "building your picture" for 1 or 2
    pulses, "--" for none, null at 3 or more. timestamp is when this view was
    computed (the app may show "as of").
    """

    model_config = ConfigDict(use_enum_values=True)

    chapter: Chapter
    score: Optional[int] = Field(default=None, ge=_MIN_LCI, le=_MAX_LCI)
    trajectory: Trajectory
    pulse_count: int = Field(default=0, ge=0)
    label: Optional[str] = None
    timestamp: datetime


class OverallLci(BaseModel):
    """The overall Life Continuity Index for the current user (section 4.8).

    score is the equal-weighted mean of the chapter scores that have at least one
    pulse, or null until any chapter does (rendered "--"). trajectory is the weekly
    band for the overall score vs 7 days prior. chapters_included lists the chapter
    codes that contributed a score (the ones with a pulse), so the app can show what
    the overall is built from. label is the section 4.8 sparse-data label for the
    overall (building_picture while fewer than 3 pulses exist across the included
    chapters, "--" when none). timestamp is when this view was computed.
    """

    model_config = ConfigDict(use_enum_values=True)

    score: Optional[int] = Field(default=None, ge=_MIN_LCI, le=_MAX_LCI)
    trajectory: Trajectory
    chapters_included: List[Chapter] = Field(default_factory=list)
    label: Optional[str] = None
    timestamp: datetime


# ---------------------------------------------------------------------------
# Check-in history (GET /api/v1/lci/history): the DISCRETE recorded LCI points
# the "Your check-in history" view renders, the de-risked "timeline" (the
# researcher's build-with-conditions verdict, Decisions.md D13 framing item +
# D15 honesty-of-direction). This is a READ of the stored lci_snapshot rows, NOT
# a new engine: each real check-in instant is one discrete point carrying its
# api-owned BAND (section 4.3 zone, never a precise plotted altitude). The app
# renders exactly these points; it draws no continuous line through a stale gap,
# infers no slope below three readings, and computes no band of its own.
# ---------------------------------------------------------------------------

# The scope a series is for: the overall index, or one Life Chapter code. A plain
# Literal "overall" plus the six chapter codes (the app keys the per-chapter rows
# off the chapter code and the overall off the "overall" literal).
LciScope = Union[Literal["overall"], Chapter]


class LciHistoryPoint(BaseModel):
    """One DISCRETE recorded LCI reading at its real check-in instant (section 4.8 history).

    A single stored lci_snapshot, surfaced as a point on the check-in history view. It
    carries the real timestamp the reading was recorded (`taken_at`, NOT an interpolated
    or evenly-spaced x), the whole-number 0 to 100 `score`, and the api-owned `band` (the
    section 4.3 zone the app reads it as, never a 2-significant-figure altitude). The app
    plots a dot at `taken_at` coloured by `band`; it never re-derives the band or the
    score.
    """

    model_config = ConfigDict(use_enum_values=True)

    taken_at: datetime
    score: int = Field(ge=_MIN_LCI, le=_MAX_LCI)
    band: LciBand


class LciSeries(BaseModel):
    """One scope's DISCRETE check-in history: the points + the honesty signals (section 4.8).

    The api owns every honesty decision the view depends on, so the app cannot lie by
    accident:
      scope            "overall" or a Life Chapter code (the app labels it).
      points           the recorded readings, time-ascending, each a discrete instant +
                       band (NEVER a continuous line; the app draws dots, and a joined
                       segment only when reading_count >= 3, the three-reading floor).
      reading_count    how many real readings exist. Below 3 the app shows no line/slope
                       (the "building your picture" state); this is the floor, owned here
                       so the app never infers a trend from one or two points.
      latest_taken_at  the instant of the last real reading (null when there are none).
                       After it the series STOPS; the app shows a muted "no reading since
                       [date]" state and never carries the last score forward as a solid
                       in-band line.
      is_stale         api-computed: the last reading is older than the staleness window,
                       so the series is out of date (the app degrades to the muted
                       no-reading-since state). Stale = stop, do not lie (D15 in time).
    """

    model_config = ConfigDict(use_enum_values=True)

    scope: LciScope
    points: List[LciHistoryPoint] = Field(default_factory=list)
    reading_count: int = Field(default=0, ge=0)
    latest_taken_at: Optional[datetime] = None
    is_stale: bool = False


class LciHistory(BaseModel):
    """The whole check-in history payload (GET /api/v1/lci/history) for ONE care recipient.

    The overall index series plus one series per Life Chapter (the six, in the stable
    Chapter order), each a discrete recorded history with its own honesty signals. This
    is a read of THIS recipient's stored lci_snapshot rows only (RLS + child_id scoped);
    it introduces no new score and no new decline language (any declining chapter is
    paired with the existing governed Erosion Alert framing in the app, never a bare
    falling line). `generated_at` is when the read was computed (the app may show "as
    of").
    """

    model_config = ConfigDict(use_enum_values=True)

    overall: LciSeries
    chapters: List[LciSeries] = Field(default_factory=list)
    generated_at: datetime
