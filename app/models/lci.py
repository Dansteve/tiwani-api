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

Trajectory is the engine's Trajectory enum (the app's strengthening / holding_steady
/ under_pressure / building_picture codes, no remap). Chapter codes are the Chapter
enum.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.engines.lci import Trajectory
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
