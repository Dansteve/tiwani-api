"""The Fusion Layer + Specificity Gate + enrichment (LCEEngineAddendum.md 2-6).

The engine layer ADDED ON TOP of the unchanged section 4.4 pipeline (steps 9 to 13
of the Addendum). PURE and deterministic like the rest of the LCE: same profile +
scenario moments always produce the same situated strategies, the same specificity,
and the same enrichment question. No DB, no clock, no randomness (the determinism
firewall, tests/test_engine_firewall.py). It reads the moments + the situated-copy
templates from the seed and holds no numeric score literal (the LCE no-hardcoded-score
guard, tests/test_seed.py): the gate thresholds are named bounds imported from the
model layer.

THE FUSION RULE (LCEEngineAddendum.md section 2, reconciled to the worked examples).
The Addendum's section-1 pseudocode iterates (tag x moment); its worked examples,
however, are authoritative on the COUNT: school.return_after_break emits 5 situated
strategies over its 5 moments, and health.dentist_checkup emits 4 over its 4 moments
(section 6). The only rule consistent with those counts is ONE situated strategy PER
MOMENT that has at least one active loading tag, with derived_from = that moment's
active loaders (the primary loader choosing the template). So a moment is the unit of
a situated strategy, and profile_derived == situated in this slice (only situated
strategies carry a non-empty derived_from; scenario-base and dimension-transfer do
not). This is documented as the deterministic reconciliation of the Addendum, whose
per-moment parenthetical tag pairings are illustrative (one even names CM-MIXED, a
no-score tag that loads nothing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.models.seed import (
    GATE_MIN_PROFILE_DERIVED,
    GATE_MIN_SITUATED,
    Dimension,
    ScenarioMoment,
    StrategySource,
)
from app.seed import SeedTables, load_seed
from app.seed.situated_templates_v1 import build_situated_sentence

# The four dimensions in canonical order, so the "highest-loading dimension" tiebreak
# is stable (temporal, then sensory, then logistical, then human).
_DIMENSION_ORDER: Tuple[Dimension, ...] = (
    Dimension.TEMPORAL,
    Dimension.SENSORY,
    Dimension.LOGISTICAL,
    Dimension.HUMAN,
)


@dataclass(frozen=True)
class FusedStrategy:
    """One situated strategy: a profile tag fused to a specific scenario moment.

    text is the governed situated sentence (action + specific moment + reason).
    source is always SITUATED_FUSION. derived_from is the active loading tag code(s)
    for the moment (never empty for a fused strategy). moment / moment_label name the
    scenario moment it is attached to (required for a situated strategy).
    """

    text: str
    source: StrategySource
    derived_from: Tuple[str, ...]
    moment: str
    moment_label: str


@dataclass(frozen=True)
class Specificity:
    """The Specificity Gate result (LCEEngineAddendum.md section 4).

    profile_derived = strategies whose derived_from is non-empty; situated =
    strategies whose source is situated_fusion. complete iff profile_derived meets
    GATE_MIN_PROFILE_DERIVED AND situated meets GATE_MIN_SITUATED.
    """

    profile_derived: int
    situated: int
    complete: bool


@dataclass(frozen=True)
class Enrichment:
    """The one value-first enrichment question (LCEEngineAddendum.md section 5).

    dimension is the highest-loading pressure dimension with no confirming profile
    tag; option_codes are the tag codes the carer can tap to confirm it (the service
    turns them into {code, label} options and the copy question).
    """

    dimension: Dimension
    option_codes: Tuple[str, ...]


def run_fusion(
    *,
    active_tags: Sequence[str],
    moments: Sequence[ScenarioMoment],
    child_name: str,
) -> List[FusedStrategy]:
    """Emit one situated strategy per moment that has an active loading tag (section 2).

    For each moment, in order, the active tags that load it (preserving the moment's
    loads order) are the derived_from; the first is the primary tag choosing the
    situated-copy template. A moment with no active loader emits nothing. Deterministic:
    the moment order and the loads order fix the output.
    """
    active = set(active_tags)
    strategies: List[FusedStrategy] = []
    for moment in moments:
        loaders = tuple(code for code in moment.loads if code in active)
        if not loaders:
            continue
        text = build_situated_sentence(
            list(loaders), moment.id, moment.label, child_name
        )
        strategies.append(
            FusedStrategy(
                text=text,
                source=StrategySource.SITUATED_FUSION,
                derived_from=loaders,
                moment=moment.id,
                moment_label=moment.label,
            )
        )
    return strategies


def compute_specificity(strategies: Sequence[object]) -> Specificity:
    """Run the Specificity Gate over a plan's strategies (section 4).

    Duck-typed over any strategy object exposing `.source` (a StrategySource or its
    string value) and `.derived_from` (a sequence). profile_derived counts strategies
    with a non-empty derived_from; situated counts source == situated_fusion. complete
    iff BOTH named thresholds are met.
    """
    profile_derived = sum(1 for s in strategies if getattr(s, "derived_from", None))
    situated = sum(1 for s in strategies if _is_situated(s))
    complete = (
        profile_derived >= GATE_MIN_PROFILE_DERIVED and situated >= GATE_MIN_SITUATED
    )
    return Specificity(
        profile_derived=profile_derived, situated=situated, complete=complete
    )


def _is_situated(strategy: object) -> bool:
    source = getattr(strategy, "source", None)
    value = getattr(source, "value", source)
    return value == StrategySource.SITUATED_FUSION.value


def build_enrichment(
    *,
    moments: Sequence[ScenarioMoment],
    active_tags: Sequence[str],
    seed: Optional[SeedTables] = None,
) -> Optional[Enrichment]:
    """The one value-first enrichment (section 5): the highest-loading unconfirmed dim.

    Finds the scenario's highest-loading pressure dimension that has no confirming
    active profile tag, and the tag codes in the moments that load it (the tap
    options). Returns None when there is no such dimension (nothing left to usefully
    ask), so the caller shows the best available Plan instead.
    """
    tables = seed if seed is not None else load_seed()
    load_counts, dim_tags = _dimension_loads(moments, tables)
    confirmed = _confirmed_dimensions(active_tags, tables)

    best: Optional[Dimension] = None
    best_count = 0
    for dimension in _DIMENSION_ORDER:
        if dimension in confirmed:
            continue
        count = load_counts.get(dimension, 0)
        if count > best_count:
            best = dimension
            best_count = count

    if best is None:
        return None
    return Enrichment(dimension=best, option_codes=tuple(dim_tags.get(best, ())))


def _dimension_loads(
    moments: Sequence[ScenarioMoment], seed: SeedTables
) -> Tuple[Dict[Dimension, int], Dict[Dimension, List[str]]]:
    """Per dimension: how many moment load-slots touch it, and which tags load it.

    A tag can touch more than one dimension (e.g. SN-UNPRED loads sensory AND
    temporal), so each (moment, tag) contributes to every dimension the tag affects.
    The tags-per-dimension list is first-seen order (deterministic) and deduped.
    """
    counts: Dict[Dimension, int] = {}
    tags: Dict[Dimension, List[str]] = {}
    for moment in moments:
        for code in moment.loads:
            for dimension in seed.tag_contribution([code]):
                counts[dimension] = counts.get(dimension, 0) + 1
                bucket = tags.setdefault(dimension, [])
                if code not in bucket:
                    bucket.append(code)
    return counts, tags


def _confirmed_dimensions(
    active_tags: Sequence[str], seed: SeedTables
) -> set:
    """The dimensions an active profile tag already confirms (contributes pressure to)."""
    confirmed: set = set()
    for code in active_tags:
        for dimension in seed.tag_contribution([code]):
            confirmed.add(dimension)
    return confirmed
