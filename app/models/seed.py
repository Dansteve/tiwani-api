"""Seed-data pydantic schemas (v3): the typed shapes the engine reads.

The LCE (Product.md section 4.4) cannot produce a plan without two seeded
lookups, and it reads them as DATA, never as hardcoded scores
(HardRules/Api/Modules/Engine.md, SeedData.md):

  - the SCENARIO MATRIX: per (chapter, activity) the four base
    {temporal, sensory, logistical, human} scores (each 1 to 5) plus the
    ranked strategy text for that scenario (LCE step 1 + step 7 inputs);
  - the TAG ARCHITECTURE: per tag code, the dimension(s) it intensifies and
    the modifier it adds (+1 or +2), with the per-dimension cap on the SUM of
    tag contributions enforced by the engine at apply time (LCE step 3).

These schemas are the contract both the seed loader (app/seed/) and the engine
read against, so a malformed authored row is rejected on load with a clear
error rather than silently producing a wrong score. The VALUES are authored as
a TIWANI-derived v1 (every cell has a written rationale; the whole set is
versioned and labelled pending owner ratification + clinical sign-off, Tasks
7/12); these schemas only pin the SHAPE and the hard ranges.

The four pressure dimensions are the engine's (Product.md section 4.4): temporal
(timing, waiting, duration), sensory (noise, light, crowds), logistical
(planning, equipment, novelty), human (social and communication demand).
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The hard bounds the rubric and Product.md section 4.4 fix. A base score is a
# whole number 1 to 5; a single tag's modifier is +1 or +2; the engine caps the
# SUM of tag contributions per dimension at +2 (this constant), then caps each
# dimension at 5. These are validated on load (app/seed/loader.py).
MIN_BASE_SCORE = 1
MAX_BASE_SCORE = 5
MIN_TAG_MODIFIER = 1
MAX_TAG_MODIFIER = 2
CAP_TAG_CONTRIBUTION_PER_DIMENSION = 2
MIN_TOTAL = 4  # four dimensions at the 1 floor
MAX_TOTAL = 20  # four dimensions at the 5 ceiling


class Dimension(str, Enum):
    """The four LCE pressure dimensions (Product.md section 4.4)."""

    TEMPORAL = "temporal"
    SENSORY = "sensory"
    LOGISTICAL = "logistical"
    HUMAN = "human"


class BaseScores(BaseModel):
    """The four base scores for one scenario, each a whole number 1 to 5.

    Child-agnostic by design: this is the INHERENT demand of the activity for a
    typical additional-needs child at a neutral profile. The engine then applies
    the support multiplier (step 2) and the tag modifiers (step 3) on top, so the
    base never bakes in a particular child.
    """

    model_config = ConfigDict(frozen=True)

    temporal: int = Field(..., ge=MIN_BASE_SCORE, le=MAX_BASE_SCORE)
    sensory: int = Field(..., ge=MIN_BASE_SCORE, le=MAX_BASE_SCORE)
    logistical: int = Field(..., ge=MIN_BASE_SCORE, le=MAX_BASE_SCORE)
    human: int = Field(..., ge=MIN_BASE_SCORE, le=MAX_BASE_SCORE)

    @property
    def total(self) -> int:
        """The base total (4 to 20) before any multiplier or modifier."""
        return self.temporal + self.sensory + self.logistical + self.human

    def as_dict(self) -> dict:
        return {
            Dimension.TEMPORAL.value: self.temporal,
            Dimension.SENSORY.value: self.sensory,
            Dimension.LOGISTICAL.value: self.logistical,
            Dimension.HUMAN.value: self.human,
        }


class ScenarioStrategy(BaseModel):
    """One ranked starter strategy for a scenario.

    rank is 1-based (1 is shown first). title is a short label; body is one line
    an outsider could act on (the section 4.6 Continuity Card voice). Non-clinical
    by rule (section 4.9 governs copy): no diagnosis, symptom, or treatment
    language anywhere.
    """

    model_config = ConfigDict(frozen=True)

    rank: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class ScenarioRow(BaseModel):
    """One scenario in the matrix: a (chapter, activity) with scores + strategies.

    chapter is one of the six fixed Life Chapter codes (validated against the
    Chapter enum on load, not here, so this schema stays decoupled from that
    module). activity_code is a stable identifier; activity_name is the human
    label. rationale ties the four scores to the rubric anchors in one line.
    """

    model_config = ConfigDict(frozen=True)

    chapter: str = Field(..., min_length=1)
    activity_code: str = Field(..., min_length=1)
    activity_name: str = Field(..., min_length=1)
    base_scores: BaseScores
    rationale: str = Field(..., min_length=1)
    strategies: List[ScenarioStrategy] = Field(..., min_length=1)

    @field_validator("strategies")
    @classmethod
    def _ranks_are_contiguous_from_one(
        cls, strategies: List[ScenarioStrategy]
    ) -> List[ScenarioStrategy]:
        """Strategy ranks must be 1..N with no gap or duplicate.

        The engine ranks strategies (section 4.4 step 7) and the seed provides the
        starter order; a gap or a duplicate rank is an authoring error, caught here.
        """
        ranks = sorted(s.rank for s in strategies)
        if ranks != list(range(1, len(strategies) + 1)):
            raise ValueError(
                "scenario strategy ranks must be 1..N contiguous with no "
                f"duplicates, got {ranks}"
            )
        return strategies


class TagModifierRow(BaseModel):
    """One tag's contribution: a (tag_code, dimension) with a +1 or +2 modifier.

    A tag may add to more than one dimension, so it can appear as several rows
    (one per dimension it intensifies). A tag with a 0 pressure contribution (the
    Recovery family, by the honest model in SeedData.md) has NO modifier row at
    all; it drives strategy selection, not the score. The engine caps the SUM of
    all tag contributions per dimension at +2 (CAP_TAG_CONTRIBUTION_PER_DIMENSION)
    at apply time, so a single tag's modifier here is always +1 or +2.
    """

    model_config = ConfigDict(frozen=True)

    tag_code: str = Field(..., min_length=1)
    dimension: Dimension
    modifier: int = Field(..., ge=MIN_TAG_MODIFIER, le=MAX_TAG_MODIFIER)
    rationale: str = Field(..., min_length=1)
