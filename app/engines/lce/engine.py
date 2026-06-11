"""The Life Continuity Engine core (Product.md section 4.4, AUTHORITATIVE).

A deterministic, rules-based (not AI) pure function: same inputs always produce
the same scores, total, tier, ranked strategies, and per-dimension explanations.
No DB, no clock, no randomness here. The plan service (app/services/plans.py)
calls run_engine, then persists the activity_record and schedules the Pulse (the
steps 8 and 9 that DO touch the database and the activity date); this module is
steps 1 to 7 and step 10 only.

THE EXACT SEQUENCE (section 4.4, HardRules/Api/Modules/Engine.md), in order:
  1. Base scores: seed.get_base_scores(chapter, activity_code); a custom activity
     (None) uses seed.chapter_average(chapter) and the plan says so. Whole numbers.
  2. Support multiplier (SL-LOW x1.0 / SL-MED x1.2 / SL-HIGH x1.4): applied to all
     four dimensions, ROUND each (the calc seam, scoring.apply_multiplier_and_round),
     then CAP each at 5 (scoring.cap_dimension).
  3. Permanent tag modifiers: the profile's permanent tags via
     seed.tag_contribution(permanent_tags), which already applies the +2-per-
     dimension-from-tags cap; add per dimension, CAP each at 5.
  4. Today-flag modifiers: the request's TG- flags via a SEPARATE
     seed.tag_contribution(today_flags) call, added ON TOP, CAP each at 5. The +2
     cap is on PERMANENT tags only (step 3); today flags are capped only at 5, so a
     today flag can push a dimension to 5 even past the +2 the permanent tags added.
     Steps 3 and 4 are kept as two separate tag_contribution calls precisely so the
     +2 cap does not bleed across them.
  5. Total = sum of the four (range 4 to 20).
  6. Tier from the total band (tier_for_total): 4 to 8 Full, 9 to 13 Modified, 14
     to 20 Pivot. The engine RECOMPUTES the tier here; it never reads a scenario's
     stored tier (that is a transcription artefact, validated to match the band).
  7. Rank strategies (strategies.rank_strategies): the scenario's seeded strategies,
     high-dimension matches first; the promotion / suppression / cross-context layer
     is the Task 9 hook.
 10. Per-dimension one-line explanations (explanations.build_dimension_explanations):
     a short non-clinical sentence each (section 4.9 governs the copy).

The engine reads the seed through SeedTables (get_base_scores, chapter_average,
tag_contribution, get_strategies); it never hardcodes a score (the SeedData.md
hard rule, asserted by a pytest guard over this package).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.engines.lce.explanations import build_dimension_explanations
from app.engines.lce.scoring import apply_multiplier_and_round, cap_dimension
from app.engines.lce.strategies import RankedStrategy, rank_strategies
from app.models.seed import BaseScores, Dimension, Tier, tier_for_total
from app.seed import SeedTables
from app.seed.tag_architecture_v1 import SUPPORT_MULTIPLIERS

# The four dimensions in their canonical order, so every result dict and every
# total iterates the dimensions identically (determinism).
_DIMENSION_ORDER = (
    Dimension.TEMPORAL,
    Dimension.SENSORY,
    Dimension.LOGISTICAL,
    Dimension.HUMAN,
)


@dataclass(frozen=True)
class EngineResult:
    """The pure output of the engine (no persistence, no schedule).

    scores are the final capped per-dimension scores (section 4.4 step 4 output).
    base_scores are the step-1 base (stored on the activity_record for audit).
    total/tier follow from scores. strategies is the section 4.4 step 7 ranked
    list. dimension_explanations is one non-clinical sentence per dimension (step
    10). used_chapter_average is True when the activity was custom and the base
    came from the chapter average (the plan tells the Coordinator so).
    activity_name is the seeded scenario name, or a generated label for a custom
    activity.
    """

    base_scores: Dict[Dimension, int]
    scores: Dict[Dimension, int]
    total: int
    tier: Tier
    strategies: List[RankedStrategy]
    dimension_explanations: Dict[str, str]
    used_chapter_average: bool
    activity_name: str


def dimensions_for_tag(tag_code: str) -> List[Dimension]:
    """The dimensions a single tag contributes to (used by the explanations).

    Reads the same seed lookup the engine scores through, so the explanation's
    "which factor lifted this dimension" matches exactly what step 3/4 added. A
    no-score tag (e.g. RC-SHORT, the strategy-only CM tags) returns an empty list.
    """
    contribution = _seed().tag_contribution([tag_code])
    return list(contribution.keys())


def run_engine(
    *,
    chapter: str,
    activity_code: str,
    support_level_code: Optional[str],
    permanent_tags: List[str],
    today_flags: List[str],
    seed: Optional[SeedTables] = None,
) -> EngineResult:
    """Run the section 4.4 sequence (steps 1 to 7 + 10) and return the result.

    support_level_code is the child's SL-LOW/MED/HIGH; a missing or unknown level
    falls back to the x1.0 (SL-LOW) multiplier, so the engine never fails on an
    incomplete profile (it just applies no uplift). permanent_tags are the child's
    profile tags; today_flags are the request's TG- flags. seed defaults to the
    loaded SeedTables (injectable for tests).
    """
    tables = seed if seed is not None else _seed()

    # --- step 1: base scores (or the chapter average for a custom activity) -----
    base = tables.get_base_scores(chapter, activity_code)
    used_chapter_average = base is None
    if base is None:
        base = tables.chapter_average(chapter)
    base_by_dim = _as_dim_map(base)

    activity_name = _resolve_activity_name(
        tables, chapter, activity_code, used_chapter_average
    )

    # --- step 2: support multiplier, round each, cap each at 5 ------------------
    multiplier = SUPPORT_MULTIPLIERS.get(support_level_code or "", SUPPORT_MULTIPLIERS["SL-LOW"])
    scores: Dict[Dimension, int] = {
        dim: cap_dimension(apply_multiplier_and_round(base_by_dim[dim], multiplier))
        for dim in _DIMENSION_ORDER
    }

    # --- step 3: permanent tag modifiers (already +2-capped), cap each at 5 -----
    permanent_contribution = tables.tag_contribution(permanent_tags)
    scores = {
        dim: cap_dimension(scores[dim] + permanent_contribution.get(dim, 0))
        for dim in _DIMENSION_ORDER
    }

    # --- step 4: today-flag modifiers (separate call; on top), cap each at 5 ----
    # A SEPARATE tag_contribution call so the +2 cap from step 3 does not include
    # the today flags: today flags are capped only at 5 and may push a dimension
    # one or more points past where the permanent +2 cap stopped.
    today_contribution = tables.tag_contribution(today_flags)
    scores = {
        dim: cap_dimension(scores[dim] + today_contribution.get(dim, 0))
        for dim in _DIMENSION_ORDER
    }

    # --- step 5: total ----------------------------------------------------------
    total = sum(scores[dim] for dim in _DIMENSION_ORDER)

    # --- step 6: tier from the band (recomputed, never read from the scenario) --
    tier = tier_for_total(total)

    # --- step 7: rank strategies (Task 9 hook left at its defaults) -------------
    starter_strategies = tables.get_strategies(chapter, activity_code)
    ranked = rank_strategies(starter_strategies, scores)

    # --- step 10: per-dimension non-clinical explanations -----------------------
    explanations = build_dimension_explanations(
        scores, permanent_tags, today_flags, used_chapter_average
    )

    return EngineResult(
        base_scores=base_by_dim,
        scores=scores,
        total=total,
        tier=tier,
        strategies=ranked,
        dimension_explanations=explanations,
        used_chapter_average=used_chapter_average,
        activity_name=activity_name,
    )


def _as_dim_map(base: BaseScores) -> Dict[Dimension, int]:
    """The BaseScores as a {Dimension: int} map in canonical order."""
    return {
        Dimension.TEMPORAL: base.temporal,
        Dimension.SENSORY: base.sensory,
        Dimension.LOGISTICAL: base.logistical,
        Dimension.HUMAN: base.human,
    }


def _resolve_activity_name(
    tables: SeedTables, chapter: str, activity_code: str, used_chapter_average: bool
) -> str:
    """The seeded scenario name, or a readable label for a custom activity."""
    if not used_chapter_average:
        for row in tables.scenarios:
            if row.chapter == chapter and row.activity_code == activity_code:
                return row.activity_name
    # Custom activity: turn the code into a readable label (no seeded name exists).
    return activity_code.replace("-", " ").replace("_", " ").strip().capitalize()


def _seed() -> SeedTables:
    """Load the validated seed once and cache it for the process.

    The seed is immutable reference data; loading it once and reusing it keeps the
    engine well under the section 4.4 step 10 "under 3 seconds" budget (the work is
    then a handful of dict operations).
    """
    global _SEED_CACHE
    if _SEED_CACHE is None:
        from app.seed import load_seed

        _SEED_CACHE = load_seed()
    return _SEED_CACHE


_SEED_CACHE: Optional[SeedTables] = None
