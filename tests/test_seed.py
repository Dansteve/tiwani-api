"""Tests for the TIWANI-derived v1 seed (Knowledge Base + Tag Architecture).

These pin the contract the engine relies on (Product.md section 4.4 inputs,
HardRules/Api/Modules/SeedData.md) without a live Supabase:

  - the seed loads and validates (load_seed succeeds, versions stamped);
  - a malformed row is REJECTED (hard-fail, not silent): a base score out of
    range, an out-of-range tag modifier, an unknown chapter, a duplicate scenario,
    a thin chapter, an unknown tag code, and a 0-pressure family carrying a row;
  - a spot-check scenario returns EXACTLY the authored base scores;
  - the +2 tag cap is enforced when tags STACK on a dimension (section 4.4 step 3);
  - every fixed chapter has at least the minimum scenarios;
  - every authored tag-modifier code resolves to the recovered taxonomy, and the
    single-select families (CM-/RC-) and the 0-pressure family (RC-) behave;
  - the engine reads seeded rows and HARDCODES no score (a guard over
    app/engines/lce/ source);
  - the DB-write path validates first and writes the expected row counts (against
    a fake client, no live Supabase).

The authored values are a TIWANI-derived v1 (SeedData.md); these tests pin the
SHAPE, the validation, and a few representative numbers, so a later owner-ratified
change is a deliberate edit to a failing pin, not a silent drift.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path

import pytest

from app.models.chapters_v3 import Chapter
from app.models.child_profile import Tag
from app.models.seed import (
    CAP_TAG_CONTRIBUTION_PER_DIMENSION,
    BaseScores,
    Dimension,
    ScenarioRow,
    ScenarioStrategy,
    TagModifierRow,
)
from app.seed import load_seed, write_seed_to_db
from app.seed.knowledge_base_v1 import ALL_SCENARIOS
from app.seed.loader import (
    MIN_SCENARIOS_PER_CHAPTER,
    SeedTables,
    SeedValidationError,
    _validate_scenarios,
    _validate_tag_modifiers,
)
from app.seed.tag_architecture_v1 import TAG_MODIFIER_ROWS

# ---------------------------------------------------------------------------
# Load + version
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tables() -> SeedTables:
    return load_seed()


def test_seed_loads_and_is_versioned(tables: SeedTables):
    assert tables.knowledge_base_version == "knowledge_base_v1"
    assert tables.tag_architecture_version == "tag_architecture_v1"
    # The provenance label is carried with the data (pending-ratification honesty).
    assert "pending owner ratification" in tables.knowledge_base_provenance
    assert "pending owner ratification" in tables.tag_architecture_provenance


def test_every_chapter_meets_the_minimum(tables: SeedTables):
    counts = Counter(s.chapter for s in tables.scenarios)
    for chapter in Chapter:
        assert counts[chapter.value] >= MIN_SCENARIOS_PER_CHAPTER, chapter.value


def test_all_six_fixed_chapters_present(tables: SeedTables):
    present = {s.chapter for s in tables.scenarios}
    assert present == {c.value for c in Chapter}


# ---------------------------------------------------------------------------
# Spot-check authored base scores (pins a few representative numbers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chapter, activity_code, expected",
    [
        # Flight is the heaviest travel scenario: 5/5/5/4.
        ("travel", "flight", {"temporal": 5, "sensory": 5, "logistical": 5, "human": 4}),
        # Haircut: short, sensory-heavy, low logistics.
        ("family", "haircut", {"temporal": 2, "sensory": 4, "logistical": 2, "human": 3}),
        # Fire drill: the sensory spike scenario (alarm), low elsewhere.
        ("school", "fire-drill", {"temporal": 2, "sensory": 5, "logistical": 1, "human": 2}),
        # First interview: human-demand peak with a quiet room.
        ("career", "first-interview", {"temporal": 3, "sensory": 2, "logistical": 3, "human": 5}),
    ],
)
def test_spot_check_base_scores(tables: SeedTables, chapter, activity_code, expected):
    scores = tables.get_base_scores(chapter, activity_code)
    assert scores is not None, f"{chapter}/{activity_code} missing"
    assert scores.as_dict() == expected


def test_custom_activity_returns_none_for_fallback(tables: SeedTables):
    # A custom activity (no row) returns None so the engine uses the chapter
    # average (section 4.4 step 1).
    assert tables.get_base_scores("school", "no-such-activity") is None


def test_chapter_average_is_whole_numbers_in_range(tables: SeedTables):
    for chapter in Chapter:
        avg = tables.chapter_average(chapter.value)
        for value in avg.as_dict().values():
            assert isinstance(value, int)
            assert 1 <= value <= 5


def test_strategies_ranked_from_one(tables: SeedTables):
    strategies = tables.get_strategies("travel", "flight")
    assert [s.rank for s in strategies] == [1, 2, 3, 4, 5]
    # All scenarios carry 3 to 5 ranked strategies.
    for row in tables.scenarios:
        ranks = [s.rank for s in tables.get_strategies(row.chapter, row.activity_code)]
        assert 3 <= len(ranks) <= 5, f"{row.activity_code} has {len(ranks)} strategies"
        assert ranks == list(range(1, len(ranks) + 1))


# ---------------------------------------------------------------------------
# The +2 tag cap (section 4.4 step 3) enforced when tags STACK
# ---------------------------------------------------------------------------


def test_tag_contribution_caps_at_plus_two_when_tags_stack(tables: SeedTables):
    # SN-NOISE (+2 sensory) + SN-CROWD (+1 sensory, +1 human) + SN-LIGHT (+2 sensory)
    # sums to +5 sensory raw, which must be capped at +2 (the section 4.4 step 3
    # cap), while human is +1 (only SN-CROWD).
    contribution = tables.tag_contribution(["SN-NOISE", "SN-CROWD", "SN-LIGHT"])
    assert contribution[Dimension.SENSORY] == CAP_TAG_CONTRIBUTION_PER_DIMENSION
    assert contribution[Dimension.SENSORY] == 2
    assert contribution[Dimension.HUMAN] == 1


def test_single_tag_contribution(tables: SeedTables):
    # CM-NONVERBAL is the +2 human communication tag.
    assert tables.tag_contribution(["CM-NONVERBAL"]) == {Dimension.HUMAN: 2}


def test_recovery_tags_contribute_nothing(tables: SeedTables):
    # The honest model: Recovery is 0-pressure (drives strategy, not score).
    for code in ("RC-SHORT", "RC-MOD", "RC-EXT", "RC-VAR"):
        assert tables.tag_contribution([code]) == {}


def test_two_dimension_tag_adds_to_both(tables: SeedTables):
    # TR-NEW adds +1 logistical and +1 human.
    assert tables.tag_contribution(["TR-NEW"]) == {
        Dimension.LOGISTICAL: 1,
        Dimension.HUMAN: 1,
    }


# ---------------------------------------------------------------------------
# Every authored tag code resolves to the recovered taxonomy
# ---------------------------------------------------------------------------


def test_every_authored_tag_code_is_in_the_taxonomy():
    valid = {t.value for t in Tag}
    for mod in TAG_MODIFIER_ROWS:
        assert mod.tag_code in valid, mod.tag_code


def test_communication_is_single_select_in_the_table():
    # At most one CM- modifier per dimension (single-select family); since CM- only
    # maps to human, there is at most one CM- row per code.
    cm_rows = [m for m in TAG_MODIFIER_ROWS if m.tag_code.startswith("CM-")]
    # Each CM code appears at most once (single dimension: human).
    per_code = Counter(m.tag_code for m in cm_rows)
    assert all(count == 1 for count in per_code.values())
    # CM-VERBAL carries no row (fully verbal = 0 added demand).
    assert "CM-VERBAL" not in {m.tag_code for m in cm_rows}


def test_no_recovery_tag_has_a_modifier_row():
    assert not any(m.tag_code.startswith("RC-") for m in TAG_MODIFIER_ROWS)


# ---------------------------------------------------------------------------
# All authored copy stays non-clinical (the section 4.9 product boundary)
# ---------------------------------------------------------------------------


def test_authored_copy_uses_no_prohibited_clinical_words(tables: SeedTables):
    # Section 4.9 governs alert copy, but the non-clinical constraint is a product
    # boundary (CLAUDE.md): the seed copy a Coordinator/outsider reads stays clear
    # of the prohibited clinical vocabulary. We scan every rationale, strategy
    # title/body, and tag rationale. "anxiety disorder" is the prohibited phrase;
    # the plain word "anxious" (a normal description of nerves) is allowed, so the
    # list uses the exact prohibited terms.
    prohibited = [
        "symptom",
        "diagnos",
        "condition",
        "mental health",
        "depression",
        "anxiety disorder",
        "clinical",
        "treatment",
        "therapy",
    ]
    hits = []
    for row in tables.scenarios:
        blob = row.rationale + " " + " ".join(
            s.title + " " + s.body for s in row.strategies
        )
        blob = blob.lower()
        hits += [(row.activity_code, w) for w in prohibited if w in blob]
    for mod in tables.tag_modifiers:
        hits += [(mod.tag_code, w) for w in prohibited if w in mod.rationale.lower()]
    assert not hits, f"prohibited clinical words in authored copy: {hits}"


# ---------------------------------------------------------------------------
# Malformed rows are REJECTED (hard-fail, not silent)
# ---------------------------------------------------------------------------


def _valid_strategy() -> ScenarioStrategy:
    return ScenarioStrategy(rank=1, title="t", body="b")


def test_pydantic_rejects_out_of_range_base_score():
    # A 6 is out of the 1..5 range; pydantic refuses to build the object.
    with pytest.raises(Exception):
        BaseScores(temporal=6, sensory=1, logistical=1, human=1)


def test_pydantic_rejects_out_of_range_tag_modifier():
    # A +3 single-tag modifier is rejected (the per-tag value is +1 or +2).
    with pytest.raises(Exception):
        TagModifierRow(
            tag_code="SN-NOISE", dimension=Dimension.SENSORY, modifier=3, rationale="x"
        )


def test_validate_rejects_unknown_chapter():
    bad = ScenarioRow(
        chapter="not-a-chapter",
        activity_code="x",
        activity_name="X",
        base_scores=BaseScores(temporal=1, sensory=1, logistical=1, human=1),
        rationale="r",
        strategies=[_valid_strategy()],
    )
    with pytest.raises(SeedValidationError, match="unknown chapter"):
        _validate_scenarios(list(ALL_SCENARIOS) + [bad])


def test_validate_rejects_duplicate_scenario():
    dup = ALL_SCENARIOS[0]
    with pytest.raises(SeedValidationError, match="duplicate scenario"):
        _validate_scenarios(list(ALL_SCENARIOS) + [dup])


def test_validate_rejects_thin_chapter():
    # Only one school scenario fails the per-chapter minimum.
    one_school = [s for s in ALL_SCENARIOS if s.chapter == "school"][:1]
    with pytest.raises(SeedValidationError, match="fewer than the minimum"):
        _validate_scenarios(one_school)


def test_validate_rejects_unknown_tag_code():
    bad = TagModifierRow(
        tag_code="ZZ-FAKE", dimension=Dimension.SENSORY, modifier=1, rationale="r"
    )
    with pytest.raises(SeedValidationError, match="unknown tag code"):
        _validate_tag_modifiers(list(TAG_MODIFIER_ROWS) + [bad])


def test_validate_rejects_recovery_modifier_row():
    # A Recovery tag must not carry a pressure modifier (0-pressure family).
    bad = TagModifierRow(
        tag_code="RC-EXT", dimension=Dimension.TEMPORAL, modifier=1, rationale="r"
    )
    with pytest.raises(SeedValidationError, match="0-pressure family"):
        _validate_tag_modifiers(list(TAG_MODIFIER_ROWS) + [bad])


def test_validate_rejects_single_tag_over_the_cap():
    # Two rows for the same tag+dimension would push one tag's own contribution to
    # +3 on that dimension, over the +2 cap. (Bypass the per-field check by using
    # two separate +2 rows.)
    over = [
        TagModifierRow(
            tag_code="SN-NOISE", dimension=Dimension.SENSORY, modifier=2, rationale="r"
        ),
        TagModifierRow(
            tag_code="SN-NOISE", dimension=Dimension.SENSORY, modifier=1, rationale="r"
        ),
    ]
    with pytest.raises(SeedValidationError, match="per-dimension cap"):
        _validate_tag_modifiers(over)


# ---------------------------------------------------------------------------
# The engine reads seeded rows and HARDCODES no score
# ---------------------------------------------------------------------------


def test_engine_lce_source_hardcodes_no_score():
    # The LCE must read seeded rows, never inline a score or multiplier (SeedData.md
    # hard rule). The engine is still a stub here; this guard holds as it is
    # implemented in Task 5. We parse the LCE source with the ast module and flag
    # any NUMERIC LITERAL that appears in real executable code, which would signal a
    # hardcoded base score, multiplier, cap, or threshold. Docstrings and comments
    # are not part of the AST as code, so the spec text in the stub docstring is
    # correctly ignored; the seed sources (app/seed) are excluded by scope (they
    # ARE the data). 0 and 1 are allowed as common non-score constants (indices,
    # truthiness), so only literals >= 2 are flagged.
    import ast

    lce_dir = Path(__file__).resolve().parents[1] / "app" / "engines" / "lce"
    offenders = []
    for path in lce_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if node.value >= 2:
                    offenders.append((path.name, getattr(node, "lineno", "?"), node.value))
    assert not offenders, f"possible hardcoded scores in LCE: {offenders}"


# ---------------------------------------------------------------------------
# The DB-write path validates first and writes the expected counts
# ---------------------------------------------------------------------------


class _RecordingWriteClient:
    """A minimal fake supabase client recording inserts/deletes for write_seed_to_db.

    insert() returns a response carrying a fabricated id so the strategy children
    can attach to their scenario; the real service client returns the inserted row.
    """

    def __init__(self):
        self.inserts = Counter()
        self.deletes = Counter()
        self._seq = 0

    def table(self, name):
        return _RecordingTable(name, self)


class _RecordingResponse:
    def __init__(self, data):
        self.data = data


class _RecordingTable:
    def __init__(self, name, parent: "_RecordingWriteClient"):
        self._name = name
        self._parent = parent
        self._op = None
        self._payload = None

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        if self._op == "insert":
            self._parent.inserts[self._name] += 1
            self._parent._seq += 1
            return _RecordingResponse([{"id": f"id-{self._parent._seq}"}])
        if self._op == "delete":
            self._parent.deletes[self._name] += 1
            return _RecordingResponse([])
        return _RecordingResponse([])


def test_write_seed_to_db_writes_expected_counts():
    client = _RecordingWriteClient()
    summary = write_seed_to_db(client)

    tables = load_seed()
    expected_scenarios = len(tables.scenarios)
    expected_strategies = sum(len(s.strategies) for s in tables.scenarios)
    expected_tags = len(tables.tag_modifiers)

    assert summary == {
        "scenarios": expected_scenarios,
        "strategies": expected_strategies,
        "tag_modifiers": expected_tags,
    }
    assert client.inserts["scenario_matrix"] == expected_scenarios
    assert client.inserts["scenario_strategy"] == expected_strategies
    assert client.inserts["tag_modifier"] == expected_tags
    # Idempotency: the version's rows are cleared before re-inserting.
    assert client.deletes["scenario_matrix"] == 1
    assert client.deletes["tag_modifier"] == 1


def test_seed_tables_are_immutable(tables: SeedTables):
    # SeedTables is a frozen dataclass so the engine cannot mutate the loaded seed.
    with pytest.raises(dataclasses.FrozenInstanceError):
        tables.scenarios = ()  # type: ignore[misc]
