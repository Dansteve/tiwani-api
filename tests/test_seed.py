"""Tests for the authoritative seed (Knowledge Base + Tag Architecture v1.0).

These pin the contract the engine relies on (Product.md section 4.4 inputs,
HardRules/Api/Modules/SeedData.md) against the EXACT VERBATIM TRANSCRIPTION of the
authoritative source documents (TIWANI LCE Complete Knowledge Base v1.0 + Child
Profile Tag Architecture v1.0, April 2026), without a live Supabase:

  - the seed loads and validates (load_seed succeeds, versions stamped);
  - THE TRANSCRIPTION GUARD: every scenario's four cells SUM to the source's stated
    Total, and every tier matches its total band;
  - spot-check scenarios across different chapters return EXACTLY the authoritative
    scores + tier (the four named in the Task 2 brief, and more);
  - the corrected tag modifiers: the all-+1 Sensory family, the corrected Recovery
    (RC-SHORT 0, RC-MOD +1, RC-EXT +2, RC-VAR +1), the new Triggers TG- family;
  - the +2 tag cap is enforced when tags STACK on a dimension (section 4.4 step 3);
  - the no-score Communication tags and RC-SHORT carry no modifier (a 0 is allowed,
    not a hard-fail);
  - a malformed row is REJECTED (hard-fail, not silent): an out-of-range score, an
    out-of-range modifier, an unknown chapter, a duplicate scenario, a thin chapter,
    an unknown tag code, a no-score tag carrying a modifier, a sum that does not match
    the stated total, a tier that does not match the band;
  - the engine reads seeded rows and HARDCODES no score (a guard over the LCE source);
  - the DB-write path validates first and writes the expected row counts.
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
    Tier,
    tier_for_total,
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
from app.seed.tag_architecture_v1 import (
    NO_SCORE_COMMUNICATION_TAGS,
    SUPPORT_MULTIPLIERS,
    TAG_MODIFIER_ROWS,
    ZERO_PRESSURE_RECOVERY_TAGS,
)

# ---------------------------------------------------------------------------
# Load + version + provenance
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tables() -> SeedTables:
    return load_seed()


def test_seed_loads_and_is_versioned(tables: SeedTables):
    assert tables.knowledge_base_version == "knowledge_base_v1"
    assert tables.tag_architecture_version == "tag_architecture_v1"
    # The provenance now states the authoritative source, not a derived v1.
    assert "authoritative" in tables.knowledge_base_provenance.lower()
    assert "authoritative" in tables.tag_architecture_provenance.lower()


# ---------------------------------------------------------------------------
# Per-chapter scenario counts (the authoritative matrices)
# ---------------------------------------------------------------------------


def test_per_chapter_scenario_counts_match_the_source(tables: SeedTables):
    # The exact counts transcribed from the six chapter matrices.
    counts = Counter(s.chapter for s in tables.scenarios)
    assert dict(counts) == {
        "school": 13,
        "career": 14,
        "family": 12,
        "social": 12,
        "travel": 13,
        "culture": 10,
    }
    assert sum(counts.values()) == 74


def test_every_chapter_meets_the_minimum(tables: SeedTables):
    counts = Counter(s.chapter for s in tables.scenarios)
    for chapter in Chapter:
        assert counts[chapter.value] >= MIN_SCENARIOS_PER_CHAPTER, chapter.value


def test_all_six_fixed_chapters_present(tables: SeedTables):
    present = {s.chapter for s in tables.scenarios}
    assert present == {c.value for c in Chapter}


# ---------------------------------------------------------------------------
# THE TRANSCRIPTION GUARD: sum == stated total, and tier == band, for EVERY row
# ---------------------------------------------------------------------------


def test_every_scenario_sum_equals_the_stated_total(tables: SeedTables):
    # The core transcription check: the four base cells must sum to the Total
    # printed in the source matrix for every single scenario.
    for s in tables.scenarios:
        assert s.base_scores.total == s.stated_total, (
            f"{s.chapter}/{s.activity_code}: cells sum to {s.base_scores.total} "
            f"but stated total is {s.stated_total}"
        )


def test_every_scenario_tier_matches_its_total_band(tables: SeedTables):
    # 4..8 Full, 9..13 Modified, 14..20 Pivot (section 4.4 step 6). Holds for the
    # five matrices with a printed Tier and the Career matrix (tier derived).
    for s in tables.scenarios:
        assert s.tier == tier_for_total(s.stated_total), (
            f"{s.chapter}/{s.activity_code}: tier {s.tier.value} vs total "
            f"{s.stated_total}"
        )


# ---------------------------------------------------------------------------
# Spot-check authored base scores + tier across different chapters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chapter, activity_code, expected, tier",
    [
        # The four named in the Task 2 brief.
        (
            "career",
            "working-from-home-child-present",
            {"temporal": 4, "sensory": 4, "logistical": 4, "human": 5},
            Tier.PIVOT,
        ),
        (
            "travel",
            "airport-departure-standard",
            {"temporal": 4, "sensory": 5, "logistical": 5, "human": 3},
            Tier.PIVOT,
        ),
        (
            "family",
            "bedtime-routine-typical-evening",
            {"temporal": 3, "sensory": 2, "logistical": 2, "human": 1},
            Tier.FULL,
        ),
        (
            "social",
            "birthday-party-large-or-unfamiliar-setting",
            {"temporal": 4, "sensory": 5, "logistical": 3, "human": 4},
            Tier.PIVOT,
        ),
        # A few more across the remaining chapters.
        (
            "school",
            "parent-school-meeting-conflict-or-crisis",
            {"temporal": 4, "sensory": 1, "logistical": 3, "human": 5},
            Tier.MODIFIED,
        ),
        (
            "culture",
            "rites-of-passage-baptism-bar-mitzvah-confirmation-naming-ceremony",
            {"temporal": 4, "sensory": 4, "logistical": 3, "human": 5},
            Tier.PIVOT,
        ),
        # The lowest-pressure scenario in the whole set (a Full at total 6).
        (
            "travel",
            "car-journey-short-familiar-route-under-1-hour",
            {"temporal": 2, "sensory": 2, "logistical": 1, "human": 1},
            Tier.FULL,
        ),
        # The highest-pressure scenario in the whole set (total 19).
        (
            "travel",
            "airport-departure-child-highly-anxious-or-dysregulated",
            {"temporal": 5, "sensory": 5, "logistical": 5, "human": 4},
            Tier.PIVOT,
        ),
    ],
)
def test_spot_check_base_scores_and_tier(tables, chapter, activity_code, expected, tier):
    scores = tables.get_base_scores(chapter, activity_code)
    assert scores is not None, f"{chapter}/{activity_code} missing"
    assert scores.as_dict() == expected
    row = next(
        r for r in tables.scenarios if r.chapter == chapter and r.activity_code == activity_code
    )
    assert row.tier == tier


def test_recurring_scenario_name_is_two_distinct_rows(tables: SeedTables):
    # "Morning routine: standard school day" appears in BOTH career and school with
    # the same 3/2/3/2=10; keyed by (chapter, activity) they are two rows.
    career = tables.get_base_scores("career", "morning-routine-standard-school-day")
    school = tables.get_base_scores("school", "morning-routine-standard-school-day")
    assert career is not None and school is not None
    assert career.as_dict() == {"temporal": 3, "sensory": 2, "logistical": 3, "human": 2}
    assert school.as_dict() == career.as_dict()


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
    # Strategies are carried verbatim from the source, ranked 1..N in source order.
    for row in tables.scenarios:
        ranks = [s.rank for s in tables.get_strategies(row.chapter, row.activity_code)]
        assert len(ranks) >= 1, f"{row.activity_code} has no strategies"
        assert ranks == list(range(1, len(ranks) + 1))


def test_a_strategy_is_carried_verbatim(tables: SeedTables):
    # The first airport-standard strategy is transcribed verbatim from the source.
    strategies = tables.get_strategies("travel", "airport-departure-standard")
    assert strategies[0].body == (
        "Request hidden disability lanyard or airport assistance"
    )


# ---------------------------------------------------------------------------
# The corrected tag modifiers (authoritative values; corrections vs the derived v1)
# ---------------------------------------------------------------------------


def test_support_multipliers_are_the_source_values():
    assert SUPPORT_MULTIPLIERS == {"SL-LOW": 1.0, "SL-MED": 1.2, "SL-HIGH": 1.4}


def test_sensory_tags_are_all_plus_one(tables: SeedTables):
    # CORRECTION: every SN- tag is +1 Sensory (the derived v1 had NOISE and LIGHT at
    # +2). SN-UNPRED is the only one that also touches Temporal.
    for code in ("SN-NOISE", "SN-LIGHT", "SN-CROWD", "SN-TOUCH", "SN-TEXTURE",
                 "SN-SMELL", "SN-TASTE", "SN-TEMP"):
        assert tables.tag_contribution([code]) == {Dimension.SENSORY: 1}, code
    # SN-UNPRED is +1 Sensory AND +1 Temporal.
    assert tables.tag_contribution(["SN-UNPRED"]) == {
        Dimension.SENSORY: 1,
        Dimension.TEMPORAL: 1,
    }


def test_sn_crowd_and_touch_are_sensory_only(tables: SeedTables):
    # CORRECTION: SN-CROWD and SN-TOUCH add to Sensory ONLY (the derived v1 also
    # added +1 Human to each).
    assert tables.tag_contribution(["SN-CROWD"]) == {Dimension.SENSORY: 1}
    assert tables.tag_contribution(["SN-TOUCH"]) == {Dimension.SENSORY: 1}


def test_transition_tags_match_the_source(tables: SeedTables):
    # CORRECTIONS: TR-CHANGE is +1 to ALL FOUR; TR-WAIT is +1 Temporal; TR-LOC is
    # +1 Logistical only; TR-NEW is +1 Temporal AND +1 Sensory.
    assert tables.tag_contribution(["TR-CHANGE"]) == {
        Dimension.TEMPORAL: 1,
        Dimension.SENSORY: 1,
        Dimension.LOGISTICAL: 1,
        Dimension.HUMAN: 1,
    }
    assert tables.tag_contribution(["TR-WAIT"]) == {Dimension.TEMPORAL: 1}
    assert tables.tag_contribution(["TR-LOC"]) == {Dimension.LOGISTICAL: 1}
    assert tables.tag_contribution(["TR-SWITCH"]) == {Dimension.TEMPORAL: 1}
    assert tables.tag_contribution(["TR-END"]) == {Dimension.TEMPORAL: 1}
    assert tables.tag_contribution(["TR-NEW"]) == {
        Dimension.TEMPORAL: 1,
        Dimension.SENSORY: 1,
    }


def test_communication_tags_match_the_source(tables: SeedTables):
    # CORRECTIONS: CM-NONVERBAL is +1 Human (the derived v1 had +2); CM-AAC is +1
    # Logistical AND +1 Human; CM-ECHO is +1 Human; the rest carry NO score.
    assert tables.tag_contribution(["CM-NONVERBAL"]) == {Dimension.HUMAN: 1}
    assert tables.tag_contribution(["CM-AAC"]) == {
        Dimension.LOGISTICAL: 1,
        Dimension.HUMAN: 1,
    }
    assert tables.tag_contribution(["CM-ECHO"]) == {Dimension.HUMAN: 1}
    for code in NO_SCORE_COMMUNICATION_TAGS:
        assert tables.tag_contribution([code]) == {}, code


def test_recovery_modifiers_are_corrected(tables: SeedTables):
    # THE RC CORRECTION: only RC-SHORT is 0 (no row); RC-MOD +1, RC-EXT +2, RC-VAR +1
    # Temporal. The derived v1 wrongly made every RC- tag 0-pressure.
    assert tables.tag_contribution(["RC-SHORT"]) == {}
    assert tables.tag_contribution(["RC-MOD"]) == {Dimension.TEMPORAL: 1}
    assert tables.tag_contribution(["RC-EXT"]) == {Dimension.TEMPORAL: 2}
    assert tables.tag_contribution(["RC-VAR"]) == {Dimension.TEMPORAL: 1}


def test_trigger_family_loads_and_matches_the_source(tables: SeedTables):
    # The NEW Triggers (TG-) family (the section 4.4 "today" flags as tags).
    assert tables.tag_contribution(["TG-HUNGER"]) == {Dimension.TEMPORAL: 1}
    assert tables.tag_contribution(["TG-FATIGUE"]) == {
        Dimension.TEMPORAL: 1,
        Dimension.SENSORY: 1,
        Dimension.LOGISTICAL: 1,
        Dimension.HUMAN: 1,
    }
    assert tables.tag_contribution(["TG-ILL"]) == {
        Dimension.TEMPORAL: 2,
        Dimension.SENSORY: 2,
        Dimension.LOGISTICAL: 2,
        Dimension.HUMAN: 2,
    }
    assert tables.tag_contribution(["TG-ANXIETY"]) == {
        Dimension.HUMAN: 1,
        Dimension.SENSORY: 1,
    }
    assert tables.tag_contribution(["TG-MEDS"]) == {
        Dimension.TEMPORAL: 1,
        Dimension.SENSORY: 1,
        Dimension.LOGISTICAL: 1,
        Dimension.HUMAN: 1,
    }
    assert tables.tag_contribution(["TG-HOME"]) == {
        Dimension.TEMPORAL: 1,
        Dimension.HUMAN: 1,
    }


def test_trigger_family_codes_are_in_the_tag_enum():
    # The TG- family must be a real part of the taxonomy (added to the Tag enum).
    valid = {t.value for t in Tag}
    for code in ("TG-HUNGER", "TG-FATIGUE", "TG-ILL", "TG-ANXIETY", "TG-MEDS", "TG-HOME"):
        assert code in valid, code


def test_tag_enum_has_exactly_thirty_two_codes():
    # Five families: SN 9 + TR 6 + CM 7 + RC 4 + TG 6 = 32 (the SL multipliers are
    # the support level, not in the tag set).
    assert len([t for t in Tag]) == 32


# ---------------------------------------------------------------------------
# The +2 tag cap (section 4.4 step 3) enforced when tags STACK
# ---------------------------------------------------------------------------


def test_tag_contribution_caps_at_plus_two_when_sn_tags_stack(tables: SeedTables):
    # Three SN- tags each +1 Sensory sum to +3 raw, which must be capped at +2 (the
    # section 4.4 step 3 cap). The all-+1 family makes the cap bite at three tags.
    contribution = tables.tag_contribution(["SN-NOISE", "SN-CROWD", "SN-LIGHT"])
    assert contribution[Dimension.SENSORY] == CAP_TAG_CONTRIBUTION_PER_DIMENSION
    assert contribution[Dimension.SENSORY] == 2


def test_tag_contribution_caps_each_dimension_independently(tables: SeedTables):
    # TG-ILL (+2 all) plus TG-FATIGUE (+1 all) raw-sums to +3 on every dimension;
    # each is capped at +2 independently.
    contribution = tables.tag_contribution(["TG-ILL", "TG-FATIGUE"])
    assert contribution == {
        Dimension.TEMPORAL: 2,
        Dimension.SENSORY: 2,
        Dimension.LOGISTICAL: 2,
        Dimension.HUMAN: 2,
    }


def test_unknown_tag_contributes_nothing(tables: SeedTables):
    assert tables.tag_contribution(["ZZ-FAKE"]) == {}


# ---------------------------------------------------------------------------
# Every authored tag code resolves; the no-score families carry no row
# ---------------------------------------------------------------------------


def test_every_authored_tag_code_is_in_the_taxonomy():
    valid = {t.value for t in Tag}
    for mod in TAG_MODIFIER_ROWS:
        assert mod.tag_code in valid, mod.tag_code


def test_no_score_communication_tags_have_no_row():
    codes_with_rows = {m.tag_code for m in TAG_MODIFIER_ROWS}
    for code in NO_SCORE_COMMUNICATION_TAGS:
        assert code not in codes_with_rows, code


def test_rc_short_is_the_only_zero_pressure_recovery_tag():
    assert ZERO_PRESSURE_RECOVERY_TAGS == ["RC-SHORT"]
    codes_with_rows = {m.tag_code for m in TAG_MODIFIER_ROWS}
    assert "RC-SHORT" not in codes_with_rows
    # The other three DO carry a row.
    for code in ("RC-MOD", "RC-EXT", "RC-VAR"):
        assert code in codes_with_rows, code


def test_tag_modifier_row_count():
    # SN 10 + TR 10 + CM 4 + RC 3 + TG 17 = 44 rows.
    assert len(TAG_MODIFIER_ROWS) == 44


# ---------------------------------------------------------------------------
# All authored copy stays non-clinical (the section 4.9 product boundary)
# ---------------------------------------------------------------------------


def test_authored_copy_uses_no_prohibited_clinical_words(tables: SeedTables):
    # Section 4.9 governs alert copy, but the non-clinical constraint is a product
    # boundary (CLAUDE.md). The transcribed source copy a Coordinator/outsider reads
    # stays clear of the prohibited clinical vocabulary. The plain word "anxious" (a
    # normal description of nerves) is allowed; the list uses the exact prohibited
    # terms ("anxiety disorder", not "anxious").
    prohibited = [
        "symptom",
        "diagnos",
        "mental health",
        "depression",
        "anxiety disorder",
        "clinical",
    ]
    hits = []
    for row in tables.scenarios:
        blob = (
            row.activity_name
            + " "
            + " ".join(s.body for s in row.strategies)
        ).lower()
        hits += [(row.activity_code, w) for w in prohibited if w in blob]
    assert not hits, f"prohibited clinical words in transcribed strategy copy: {hits}"


# ---------------------------------------------------------------------------
# Malformed rows are REJECTED (hard-fail, not silent)
# ---------------------------------------------------------------------------


def _valid_strategy() -> ScenarioStrategy:
    return ScenarioStrategy(rank=1, title="t", body="b")


def _row(**overrides) -> ScenarioRow:
    base = dict(
        chapter="school",
        activity_code="x",
        activity_name="X",
        base_scores=BaseScores(temporal=1, sensory=1, logistical=1, human=1),
        stated_total=4,
        tier=Tier.FULL,
        rationale="r",
        strategies=[_valid_strategy()],
    )
    base.update(overrides)
    return ScenarioRow(**base)


def test_pydantic_rejects_out_of_range_base_score():
    with pytest.raises(Exception):
        BaseScores(temporal=6, sensory=1, logistical=1, human=1)


def test_pydantic_rejects_out_of_range_tag_modifier():
    with pytest.raises(Exception):
        TagModifierRow(
            tag_code="SN-NOISE", dimension=Dimension.SENSORY, modifier=3, rationale="x"
        )


def test_row_rejects_sum_not_equal_to_stated_total():
    # Four cells sum to 4 but the stated total says 5: a transcription error.
    with pytest.raises(Exception, match="stated total"):
        _row(stated_total=5)


def test_row_rejects_tier_not_matching_band():
    # Total 4 is a Full band, but the row claims Pivot.
    with pytest.raises(Exception, match="does not match total"):
        _row(tier=Tier.PIVOT)


def test_validate_rejects_unknown_chapter():
    bad = _row(chapter="not-a-chapter")
    with pytest.raises(SeedValidationError, match="unknown chapter"):
        _validate_scenarios(list(ALL_SCENARIOS) + [bad])


def test_validate_rejects_duplicate_scenario():
    dup = ALL_SCENARIOS[0]
    with pytest.raises(SeedValidationError, match="duplicate scenario"):
        _validate_scenarios(list(ALL_SCENARIOS) + [dup])


def test_validate_rejects_thin_chapter():
    one_school = [s for s in ALL_SCENARIOS if s.chapter == "school"][:1]
    with pytest.raises(SeedValidationError, match="fewer than the minimum"):
        _validate_scenarios(one_school)


def test_validate_rejects_unknown_tag_code():
    bad = TagModifierRow(
        tag_code="ZZ-FAKE", dimension=Dimension.SENSORY, modifier=1, rationale="r"
    )
    with pytest.raises(SeedValidationError, match="unknown tag code"):
        _validate_tag_modifiers(list(TAG_MODIFIER_ROWS) + [bad])


def test_validate_rejects_rc_short_modifier_row():
    # RC-SHORT is the 0-pressure recovery tag and must not carry a modifier row.
    bad = TagModifierRow(
        tag_code="RC-SHORT", dimension=Dimension.TEMPORAL, modifier=1, rationale="r"
    )
    with pytest.raises(SeedValidationError, match="0-pressure recovery tag"):
        _validate_tag_modifiers(list(TAG_MODIFIER_ROWS) + [bad])


def test_validate_rejects_no_score_communication_modifier_row():
    # A strategy-only CM tag (e.g. CM-VERBAL) must not carry a modifier row.
    bad = TagModifierRow(
        tag_code="CM-VERBAL", dimension=Dimension.HUMAN, modifier=1, rationale="r"
    )
    with pytest.raises(SeedValidationError, match="strategy-only communication tag"):
        _validate_tag_modifiers(list(TAG_MODIFIER_ROWS) + [bad])


def test_validate_rejects_single_tag_over_the_cap():
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
    # hard rule). We parse the LCE source with ast and flag any numeric literal >= 2
    # in executable code (docstrings/comments are not AST literals). 0 and 1 are
    # allowed as common non-score constants.
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
    """A minimal fake supabase client recording inserts/deletes for write_seed_to_db."""

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
    with pytest.raises(dataclasses.FrozenInstanceError):
        tables.scenarios = ()  # type: ignore[misc]
