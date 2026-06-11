"""The seed loader + on-load validation (hard-fail) + the engine read path.

This is what turns the authored Knowledge Base v1 (the scenario matrix) and Tag
Architecture v1 (the tag modifiers) into the validated, in-memory lookups the LCE
reads (Product.md section 4.4, HardRules/Api/Modules/Engine.md). It is the SINGLE
place the seed is assembled and checked; the engine calls load_seed() and reads the
returned tables, never a hardcoded score (SeedData.md hard rule).

VALIDATION IS HARD-FAIL, NOT SILENT (Task 2 requirement). load_seed() raises
SeedValidationError on the FIRST malformed input, with a clear message, so a bad
authored row can never reach the engine:
  - every base score is a whole number in 1..5 (pydantic enforces this per field;
    the loader re-checks defensively and reports the offending scenario);
  - every chapter in the six fixed set (Chapter enum) is present with at least the
    minimum number of scenarios;
  - every scenario's chapter code is one of the six (no orphan chapter);
  - every (chapter, activity_code) is unique (no duplicate scenario);
  - every base total lands in 4..20 (true by construction, asserted anyway);
  - every scenario has at least one strategy and the ranks are 1..N contiguous;
  - every tag modifier references a defined tag code (the recovered taxonomy);
  - every single tag modifier is +1 or +2;
  - no single tag pushes its OWN contribution to a dimension over the +2 cap (the
    cap on the SUM across stacked tags is enforced at engine apply time, below).

THE ENGINE READ PATH. load_seed() returns a SeedTables with:
  - get_base_scores(chapter, activity_code) -> BaseScores | None (LCE step 1; the
    engine falls back to the chapter average when this is None, per section 4.4);
  - chapter_average(chapter) -> BaseScores (LCE step 1 custom-activity fallback,
    rounded to whole numbers);
  - get_strategies(chapter, activity_code) -> list[ScenarioStrategy] (LCE step 7
    starter order);
  - tag_contribution(tag_codes) -> dict[Dimension,int] (LCE step 3: sums the
    modifiers of the given tags per dimension, then caps each dimension's tag
    contribution at +2). This is the ONLY place the +2-from-tags cap is applied,
    so the engine cannot get it wrong.

The seed is versioned (knowledge_base_v1, tag_architecture_v1); a value change is a
new version owned by the PRODUCT OWNER, not a code edit (SeedData.md).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.models.chapters_v3 import Chapter
from app.models.seed import (
    CAP_TAG_CONTRIBUTION_PER_DIMENSION,
    MAX_BASE_SCORE,
    MAX_TAG_MODIFIER,
    MAX_TOTAL,
    MIN_BASE_SCORE,
    MIN_TAG_MODIFIER,
    MIN_TOTAL,
    BaseScores,
    Dimension,
    ScenarioRow,
    ScenarioStrategy,
    TagModifierRow,
)
from app.seed.knowledge_base_v1 import (
    ALL_SCENARIOS,
    KNOWLEDGE_BASE_PROVENANCE,
    KNOWLEDGE_BASE_VERSION,
)
from app.seed.tag_architecture_v1 import (
    TAG_ARCHITECTURE_PROVENANCE,
    TAG_ARCHITECTURE_VERSION,
    TAG_MODIFIER_ROWS,
    ZERO_PRESSURE_FAMILIES,
)

# The minimum scenarios every chapter must carry for a usable v1 (Task 2 asks for
# ~6 to 10 per chapter). Enforced on load so a thin chapter is caught, not shipped.
MIN_SCENARIOS_PER_CHAPTER = 6


class SeedValidationError(Exception):
    """Raised when an authored seed row is malformed. Hard-fail, never silent."""


def _valid_tag_codes() -> set:
    """The defined tag vocabulary (the recovered taxonomy in app/models)."""
    from app.models.child_profile import Tag

    return {t.value for t in Tag}


@dataclass(frozen=True)
class SeedTables:
    """The validated, in-memory lookups the LCE reads. Built by load_seed()."""

    knowledge_base_version: str
    tag_architecture_version: str
    knowledge_base_provenance: str
    tag_architecture_provenance: str

    scenarios: Tuple[ScenarioRow, ...]
    tag_modifiers: Tuple[TagModifierRow, ...]

    # (chapter_code, activity_code) -> ScenarioRow
    _by_key: Dict[Tuple[str, str], ScenarioRow] = field(default_factory=dict)
    # chapter_code -> list[ScenarioRow]
    _by_chapter: Dict[str, List[ScenarioRow]] = field(default_factory=dict)
    # tag_code -> dimension -> modifier
    _tag_index: Dict[str, Dict[Dimension, int]] = field(default_factory=dict)

    # --- LCE step 1: base scores --------------------------------------------
    def get_base_scores(self, chapter: str, activity_code: str) -> Optional[BaseScores]:
        """The authored base scores for a scenario, or None for a custom activity.

        None signals the engine to use chapter_average() (section 4.4 step 1: a
        custom activity with no scenario row falls back to the chapter average and
        the plan says so).
        """
        row = self._by_key.get((chapter, activity_code))
        return row.base_scores if row else None

    def chapter_average(self, chapter: str) -> BaseScores:
        """The whole-number average of a chapter's base scores (custom fallback).

        Section 4.4 step 1 rounds base scores to whole numbers, so the fallback
        average is rounded too. Raises if the chapter has no scenarios (impossible
        after load_seed, which requires every chapter populated).
        """
        rows = self._by_chapter.get(chapter, [])
        if not rows:
            raise SeedValidationError(f"no scenarios for chapter '{chapter}'")
        n = len(rows)
        return BaseScores(
            temporal=round(sum(r.base_scores.temporal for r in rows) / n),
            sensory=round(sum(r.base_scores.sensory for r in rows) / n),
            logistical=round(sum(r.base_scores.logistical for r in rows) / n),
            human=round(sum(r.base_scores.human for r in rows) / n),
        )

    # --- LCE step 7: starter strategies -------------------------------------
    def get_strategies(self, chapter: str, activity_code: str) -> List[ScenarioStrategy]:
        """The ranked starter strategies for a scenario (empty for a custom one)."""
        row = self._by_key.get((chapter, activity_code))
        if not row:
            return []
        return sorted(row.strategies, key=lambda s: s.rank)

    # --- LCE step 3: tag contribution with the +2-per-dimension cap ----------
    def tag_contribution(self, tag_codes: List[str]) -> Dict[Dimension, int]:
        """Sum the given tags' modifiers per dimension, capped at +2 per dimension.

        This is the ONLY place the section 4.4 step 3 cap ("total tag contribution
        per dimension is capped at +2") is applied, so the engine adds a value that
        is already capped and cannot exceed +2 from tags on any dimension. Unknown
        tag codes contribute nothing (they are validated elsewhere on the profile);
        a 0-pressure tag (every Recovery tag) simply has no modifier to add.
        Returns only the dimensions that received a contribution.
        """
        raw: Dict[Dimension, int] = defaultdict(int)
        for code in tag_codes:
            for dimension, modifier in self._tag_index.get(code, {}).items():
                raw[dimension] += modifier
        return {
            dimension: min(total, CAP_TAG_CONTRIBUTION_PER_DIMENSION)
            for dimension, total in raw.items()
        }


def load_seed() -> SeedTables:
    """Assemble + validate the seed; raise SeedValidationError on any bad row.

    Called by the engine (and the seed migration step) to get the validated
    lookups. Hard-fail by design: a malformed authored row stops the load with a
    clear message rather than silently producing a wrong score.
    """
    scenarios = list(ALL_SCENARIOS)
    tag_modifiers = list(TAG_MODIFIER_ROWS)

    _validate_scenarios(scenarios)
    _validate_tag_modifiers(tag_modifiers)

    by_key: Dict[Tuple[str, str], ScenarioRow] = {}
    by_chapter: Dict[str, List[ScenarioRow]] = defaultdict(list)
    for row in scenarios:
        by_key[(row.chapter, row.activity_code)] = row
        by_chapter[row.chapter].append(row)

    tag_index: Dict[str, Dict[Dimension, int]] = defaultdict(dict)
    for mod in tag_modifiers:
        tag_index[mod.tag_code][mod.dimension] = mod.modifier

    return SeedTables(
        knowledge_base_version=KNOWLEDGE_BASE_VERSION,
        tag_architecture_version=TAG_ARCHITECTURE_VERSION,
        knowledge_base_provenance=KNOWLEDGE_BASE_PROVENANCE,
        tag_architecture_provenance=TAG_ARCHITECTURE_PROVENANCE,
        scenarios=tuple(scenarios),
        tag_modifiers=tuple(tag_modifiers),
        _by_key=by_key,
        _by_chapter=dict(by_chapter),
        _tag_index=dict(tag_index),
    )


def _validate_scenarios(scenarios: List[ScenarioRow]) -> None:
    """Hard-fail checks for the scenario matrix."""
    if not scenarios:
        raise SeedValidationError("the scenario matrix is empty")

    valid_chapters = {c.value for c in Chapter}
    seen_keys: set = set()
    counts: Dict[str, int] = defaultdict(int)

    for row in scenarios:
        # Chapter must be one of the six fixed codes (no orphan chapter).
        if row.chapter not in valid_chapters:
            raise SeedValidationError(
                f"scenario '{row.activity_code}' has unknown chapter '{row.chapter}' "
                f"(expected one of {sorted(valid_chapters)})"
            )

        # (chapter, activity_code) must be unique.
        key = (row.chapter, row.activity_code)
        if key in seen_keys:
            raise SeedValidationError(f"duplicate scenario for {key}")
        seen_keys.add(key)
        counts[row.chapter] += 1

        # Base scores in range (pydantic already enforces this; re-check so the
        # error names the scenario, not just a field).
        for name, value in row.base_scores.as_dict().items():
            if not (MIN_BASE_SCORE <= value <= MAX_BASE_SCORE):
                raise SeedValidationError(
                    f"scenario '{row.activity_code}' {name} score {value} is "
                    f"outside {MIN_BASE_SCORE}..{MAX_BASE_SCORE}"
                )

        # Base total in 4..20 (true by construction; asserted defensively).
        if not (MIN_TOTAL <= row.base_scores.total <= MAX_TOTAL):
            raise SeedValidationError(
                f"scenario '{row.activity_code}' base total {row.base_scores.total} "
                f"is outside {MIN_TOTAL}..{MAX_TOTAL}"
            )

        # At least one strategy, ranks contiguous (pydantic checks ranks; this
        # catches the empty case with a scenario-named message).
        if not row.strategies:
            raise SeedValidationError(
                f"scenario '{row.activity_code}' has no strategies (orphan scenario)"
            )

    # Every fixed chapter present with the minimum number of scenarios.
    for chapter in valid_chapters:
        if counts.get(chapter, 0) < MIN_SCENARIOS_PER_CHAPTER:
            raise SeedValidationError(
                f"chapter '{chapter}' has {counts.get(chapter, 0)} scenarios, "
                f"fewer than the minimum {MIN_SCENARIOS_PER_CHAPTER}"
            )


def _validate_tag_modifiers(tag_modifiers: List[TagModifierRow]) -> None:
    """Hard-fail checks for the tag-modifier table."""
    valid_codes = _valid_tag_codes()
    # Accumulate each tag's own contribution per dimension to enforce that NO
    # single tag exceeds the +2 cap on its own (the SUM across stacked tags is
    # capped at apply time in tag_contribution).
    per_tag_dim: Dict[Tuple[str, Dimension], int] = defaultdict(int)

    for mod in tag_modifiers:
        # Referenced tag code must be defined in the recovered taxonomy.
        if mod.tag_code not in valid_codes:
            raise SeedValidationError(
                f"tag modifier references unknown tag code '{mod.tag_code}'"
            )

        # A 0-pressure family (Recovery) must not carry a modifier row at all.
        if any(mod.tag_code.startswith(prefix) for prefix in ZERO_PRESSURE_FAMILIES):
            raise SeedValidationError(
                f"tag '{mod.tag_code}' is in a 0-pressure family "
                f"({ZERO_PRESSURE_FAMILIES}) and must not have a modifier row"
            )

        # Each single modifier is +1 or +2.
        if not (MIN_TAG_MODIFIER <= mod.modifier <= MAX_TAG_MODIFIER):
            raise SeedValidationError(
                f"tag '{mod.tag_code}' modifier {mod.modifier} on {mod.dimension.value} "
                f"is outside {MIN_TAG_MODIFIER}..{MAX_TAG_MODIFIER}"
            )

        per_tag_dim[(mod.tag_code, mod.dimension)] += mod.modifier

    # No single tag's own contribution to one dimension exceeds the +2 cap (this
    # catches an authoring slip of two rows for the same tag+dimension).
    for (tag_code, dimension), total in per_tag_dim.items():
        if total > CAP_TAG_CONTRIBUTION_PER_DIMENSION:
            raise SeedValidationError(
                f"tag '{tag_code}' contributes {total} to {dimension.value}, over the "
                f"+{CAP_TAG_CONTRIBUTION_PER_DIMENSION} per-dimension cap"
            )


def write_seed_to_db(client) -> Dict[str, int]:
    """Write the validated seed into the DB tables via a service-role client.

    The versioned seed step (the DB side of SeedData.md). It calls load_seed()
    FIRST, so the write never runs on a malformed seed (hard-fail before any row
    is inserted), then inserts the scenario_matrix rows (with their
    scenario_strategy children) and the tag_modifier rows from migration 0002.

    The client is the supabase service-role client (app/db.get_service_client()):
    these are GLOBAL reference tables with no user write policy, so the write must
    bypass RLS, which the service-role key does. The orchestrator gates the
    PRODUCTION apply deliberately (Decisions.md D12, like the earlier migrations);
    this function is the mechanism, not an instruction to run it against
    production. It is idempotent on (seed_version): it deletes any existing rows
    for the seed's version first, so a re-run replaces rather than duplicates.

    Returns a small count summary {scenarios, strategies, tag_modifiers}.
    """
    tables = load_seed()
    kb_version = tables.knowledge_base_version
    tag_version = tables.tag_architecture_version

    # Idempotency: clear this version's rows first (cascade removes the strategies
    # of any scenario we delete). Re-running a seed version replaces it cleanly.
    client.table("scenario_matrix").delete().eq("seed_version", kb_version).execute()
    client.table("tag_modifier").delete().eq("seed_version", tag_version).execute()

    scenario_count = 0
    strategy_count = 0
    for row in tables.scenarios:
        inserted = client.table("scenario_matrix").insert(
            {
                "seed_version": kb_version,
                "chapter": row.chapter,
                "activity_code": row.activity_code,
                "activity_name": row.activity_name,
                "temporal": row.base_scores.temporal,
                "sensory": row.base_scores.sensory,
                "logistical": row.base_scores.logistical,
                "human": row.base_scores.human,
                "rationale": row.rationale,
            }
        ).execute()
        scenario_count += 1

        scenario_id = _inserted_id(inserted)
        if scenario_id is not None:
            for strat in sorted(row.strategies, key=lambda s: s.rank):
                client.table("scenario_strategy").insert(
                    {
                        "scenario_id": scenario_id,
                        "rank": strat.rank,
                        "title": strat.title,
                        "body": strat.body,
                    }
                ).execute()
                strategy_count += 1

    tag_count = 0
    for mod in tables.tag_modifiers:
        client.table("tag_modifier").insert(
            {
                "seed_version": tag_version,
                "tag_code": mod.tag_code,
                "dimension": mod.dimension.value,
                "modifier": mod.modifier,
                "rationale": mod.rationale,
            }
        ).execute()
        tag_count += 1

    return {
        "scenarios": scenario_count,
        "strategies": strategy_count,
        "tag_modifiers": tag_count,
    }


def _inserted_id(response) -> Optional[str]:
    """Pull the id of the just-inserted row from a Supabase insert response."""
    data = getattr(response, "data", None)
    if isinstance(data, list) and data:
        return data[0].get("id")
    if isinstance(data, dict):
        return data.get("id")
    return None
