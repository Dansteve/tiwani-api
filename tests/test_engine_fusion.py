"""Table-driven tests for the Fusion Layer + Specificity Gate + enrichment.

Pins the AUTHORITATIVE LCEEngineAddendum.md engine additions (steps 9 to 13) to the
exact numbers of the three worked examples in section 6, plus the fusion rule, the
provenance schema, and the gate boundaries. Pure functions of their inputs, so no live
Supabase is needed (these call run_fusion / compute_specificity / build_enrichment
directly); the service-level enrichment loop is exercised with a fake Supabase client.

The three worked examples (LCEEngineAddendum.md section 6), which the BuildPlan contract
names as the fixtures (school PASS 5/5, dentist PASS 4/4, new-user FAIL -> enrich -> PASS):
  - Example 1 school.return_after_break, child Tio: gate PASS, profile_derived 5 / situated 5.
  - Example 2 health.dentist_checkup, same child: gate PASS, profile_derived 4 / situated 4.
  - Example 3 new user, dentist, NO tags: gate FAIL (0/0) -> one sensory enrichment ->
    tags that span two moments -> re-run -> PASS.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.services.plans as plans_service
from app.auth import AuthedUser
from app.engines.alerts.guard import find_prohibited_words
from app.engines.lce import build_enrichment, compute_specificity, run_fusion
from app.models.seed import Dimension, StrategySource
from app.seed import load_seed
from app.seed.scenario_moments_v1 import (
    DENTIST_CHECKUP,
    SCHOOL_RETURN_AFTER_BREAK,
    TIO_TAGS,
)
from app.seed.situated_templates_v1 import TAG_LABEL, all_copy_strings
from tests.fakes_supabase import FakeClient, FakeResponse

CHILD_NAME = "Tio"


# ---------------------------------------------------------------------------
# The three Addendum worked examples (section 6) as table-driven fixtures
# ---------------------------------------------------------------------------


def test_example_1_school_return_after_break_gate_passes_5_5():
    situated = run_fusion(
        active_tags=TIO_TAGS,
        moments=SCHOOL_RETURN_AFTER_BREAK.moments,
        child_name=CHILD_NAME,
    )
    # One situated strategy per moment (all five moments have an active loader).
    assert len(situated) == 5
    spec = compute_specificity(situated)
    assert spec.profile_derived == 5
    assert spec.situated == 5
    assert spec.complete is True
    # Each situated strategy is attached to a distinct moment in scenario order.
    assert [s.moment for s in situated] == [
        "arrival",
        "assembly",
        "lining_up",
        "cloakroom",
        "end_of_day",
    ]


def test_example_2_dentist_checkup_gate_passes_4_4():
    situated = run_fusion(
        active_tags=TIO_TAGS,
        moments=DENTIST_CHECKUP.moments,
        child_name=CHILD_NAME,
    )
    assert len(situated) == 4
    spec = compute_specificity(situated)
    assert spec.profile_derived == 4
    assert spec.situated == 4
    assert spec.complete is True
    # The chair moment loads SN-TOUCH too, but Tio has no touch tag, so the chair's
    # derived_from is only the three active sensory tags (not SN-TOUCH).
    chair = next(s for s in situated if s.moment == "chair")
    assert "SN-TOUCH" not in chair.derived_from
    assert set(chair.derived_from) == {"SN-LIGHT", "SN-NOISE", "SN-UNPRED"}


def test_example_3_new_user_dentist_fails_then_enriches_to_pass():
    # No active tags: the gate FAILS (0/0), the old build's generic-plan trap.
    situated = run_fusion(
        active_tags=[], moments=DENTIST_CHECKUP.moments, child_name=CHILD_NAME
    )
    assert situated == []
    spec = compute_specificity(situated)
    assert (spec.profile_derived, spec.situated, spec.complete) == (0, 0, False)

    # One value-first enrichment: the highest-loading UNCONFIRMED dimension is Sensory.
    enrichment = build_enrichment(moments=DENTIST_CHECKUP.moments, active_tags=[])
    assert enrichment is not None
    assert enrichment.dimension is Dimension.SENSORY
    # The tap options are the sensory-loading tags in the dentist moments.
    assert set(enrichment.option_codes) == {
        "SN-CROWD",
        "SN-UNPRED",
        "SN-LIGHT",
        "SN-NOISE",
        "SN-TOUCH",
    }

    # The carer confirms sensory sensitivities that span two moments (waiting room +
    # chair); re-running fusion now PASSES the gate (2 situated => profile_derived 2).
    enriched = run_fusion(
        active_tags=["SN-CROWD", "SN-LIGHT"],
        moments=DENTIST_CHECKUP.moments,
        child_name=CHILD_NAME,
    )
    spec_after = compute_specificity(enriched)
    assert spec_after.profile_derived == 2
    assert spec_after.situated == 2
    assert spec_after.complete is True


def test_enrichment_that_hits_one_moment_still_fails_the_gate():
    # SN-LIGHT + SN-NOISE both load ONLY the chair moment, so fusion emits ONE situated
    # strategy (one per moment): profile_derived 1 < 2, so the gate is still not complete
    # and the caller shows the honest "still getting to know" state.
    enriched = run_fusion(
        active_tags=["SN-LIGHT", "SN-NOISE"],
        moments=DENTIST_CHECKUP.moments,
        child_name=CHILD_NAME,
    )
    assert len(enriched) == 1
    assert compute_specificity(enriched).complete is False


# ---------------------------------------------------------------------------
# The fusion rule (LCEEngineAddendum.md section 2): one situated per loaded moment
# ---------------------------------------------------------------------------


def test_fusion_emits_one_situated_strategy_per_loaded_moment():
    situated = run_fusion(
        active_tags=["SN-CROWD"],
        moments=SCHOOL_RETURN_AFTER_BREAK.moments,
        child_name=CHILD_NAME,
    )
    # SN-CROWD loads arrival, assembly and lining_up (three moments), so three situated.
    assert [s.moment for s in situated] == ["arrival", "assembly", "lining_up"]


def test_fusion_skips_a_moment_with_no_active_loader():
    # SN-LIGHT loads only the assembly moment of the school scenario.
    situated = run_fusion(
        active_tags=["SN-LIGHT"],
        moments=SCHOOL_RETURN_AFTER_BREAK.moments,
        child_name=CHILD_NAME,
    )
    assert len(situated) == 1
    assert situated[0].moment == "assembly"


def test_fusion_derived_from_preserves_moment_loads_order():
    # arrival loads [SN-CROWD, SN-NOISE, SN-UNPRED]; with all three active the
    # derived_from keeps that order (the first is the template's primary tag).
    situated = run_fusion(
        active_tags=["SN-UNPRED", "SN-NOISE", "SN-CROWD"],
        moments=SCHOOL_RETURN_AFTER_BREAK.moments,
        child_name=CHILD_NAME,
    )
    arrival = next(s for s in situated if s.moment == "arrival")
    assert arrival.derived_from == ("SN-CROWD", "SN-NOISE", "SN-UNPRED")


def test_fusion_is_deterministic():
    kwargs = dict(
        active_tags=TIO_TAGS,
        moments=DENTIST_CHECKUP.moments,
        child_name=CHILD_NAME,
    )
    first = run_fusion(**kwargs)
    second = run_fusion(**kwargs)
    assert [(s.moment, s.derived_from, s.text) for s in first] == [
        (s.moment, s.derived_from, s.text) for s in second
    ]


# ---------------------------------------------------------------------------
# Provenance (LCEEngineAddendum.md section 3)
# ---------------------------------------------------------------------------


def test_situated_strategy_carries_situated_fusion_provenance():
    situated = run_fusion(
        active_tags=["SN-CROWD"],
        moments=SCHOOL_RETURN_AFTER_BREAK.moments,
        child_name=CHILD_NAME,
    )
    s = situated[0]
    assert s.source is StrategySource.SITUATED_FUSION
    assert s.derived_from == ("SN-CROWD",)  # non-empty for a fused strategy
    assert s.moment == "arrival"
    assert s.moment_label == "Arrival / playground"
    assert s.text.strip()  # a real situated sentence


def test_strategy_source_enum_values_match_the_contract():
    assert StrategySource.SCENARIO_BASE.value == "scenario_base"
    assert StrategySource.DIMENSION_TRANSFER.value == "dimension_transfer"
    assert StrategySource.SITUATED_FUSION.value == "situated_fusion"


# ---------------------------------------------------------------------------
# The Specificity Gate boundaries (section 4): profile_derived >= 2 AND situated >= 1
# ---------------------------------------------------------------------------


class _Strat:
    """A duck-typed strategy stub: only .source and .derived_from are read by the gate."""

    def __init__(self, source: StrategySource, derived_from):
        self.source = source
        self.derived_from = list(derived_from)


_SITUATED = lambda: _Strat(StrategySource.SITUATED_FUSION, ["SN-CROWD"])  # noqa: E731
# A profile-derived-but-not-situated stub (a hypothetical tag-derived transfer), to prove
# the two gate conditions are counted INDEPENDENTLY.
_DERIVED_ONLY = lambda: _Strat(StrategySource.DIMENSION_TRANSFER, ["SN-NOISE"])  # noqa: E731
_BASE = lambda: _Strat(StrategySource.SCENARIO_BASE, [])  # noqa: E731


@pytest.mark.parametrize(
    "strategies, profile_derived, situated, complete",
    [
        # PASS: two profile-derived, at least one situated (the min pass).
        ([_SITUATED(), _SITUATED()], 2, 2, True),
        # FAIL: only one profile-derived (< 2), even though it is situated.
        ([_SITUATED()], 1, 1, False),
        # FAIL: two profile-derived but NONE situated (situated < 1).
        ([_DERIVED_ONLY(), _DERIVED_ONLY()], 2, 0, False),
        # PASS: two profile-derived of which one is situated (the two conditions met apart).
        ([_SITUATED(), _DERIVED_ONLY()], 2, 1, True),
        # FAIL: scenario-base only is never profile-derived.
        ([_BASE(), _BASE(), _BASE()], 0, 0, False),
    ],
)
def test_gate_boundaries(strategies, profile_derived, situated, complete):
    spec = compute_specificity(strategies)
    assert spec.profile_derived == profile_derived
    assert spec.situated == situated
    assert spec.complete is complete


# ---------------------------------------------------------------------------
# Enrichment: highest-loading unconfirmed dimension (section 5)
# ---------------------------------------------------------------------------


def test_enrichment_skips_a_confirmed_dimension():
    # If sensory is already confirmed (an active SN- tag contributes to it), enrichment
    # moves to the next highest-loading UNCONFIRMED dimension (temporal for the dentist).
    enrichment = build_enrichment(
        moments=DENTIST_CHECKUP.moments, active_tags=["SN-CROWD"]
    )
    assert enrichment is not None
    assert enrichment.dimension is Dimension.TEMPORAL
    # Temporal loaders in the dentist moments: TR-WAIT, SN-UNPRED, RC-MOD.
    assert set(enrichment.option_codes) == {"TR-WAIT", "SN-UNPRED", "RC-MOD"}


def test_enrichment_is_none_when_every_loaded_dimension_is_confirmed():
    # A one-moment scenario whose only load is TR-LOC (logistical): confirming TR-LOC
    # leaves nothing else to usefully ask, so there is no enrichment.
    enrichment = build_enrichment(
        moments=[DENTIST_CHECKUP.moments[0]], active_tags=["TR-LOC"]
    )
    assert enrichment is None


# ---------------------------------------------------------------------------
# Governed copy stays non-clinical (LCEEngineAddendum.md governed-copy note, 4.9)
# ---------------------------------------------------------------------------


def test_situated_and_enrichment_copy_is_non_clinical():
    for text in all_copy_strings():
        assert not find_prohibited_words(text), text


def test_every_option_code_has_a_human_label():
    # The enrichment options render a label; the sensory options for the dentist must all
    # resolve to a human label (never a raw code shown to a carer).
    enrichment = build_enrichment(moments=DENTIST_CHECKUP.moments, active_tags=[])
    for code in enrichment.option_codes:
        assert TAG_LABEL.get(code), code


# ---------------------------------------------------------------------------
# Seeded scenario moments are loaded + validated
# ---------------------------------------------------------------------------


def test_seeded_scenario_moments_load_for_the_authored_scenarios():
    tables = load_seed()
    # The birthday party gained moments (BuildPlan Wave-1 ~6 scenarios).
    moments = tables.get_moments("social", "birthday-party-small-familiar-children")
    assert [m.id for m in moments] == ["arrival", "games", "food_and_cake", "goodbye"]
    # A scenario with no authored moments yet returns an empty list (no situated output).
    assert tables.get_moments("family", "bedtime-routine-typical-evening") == []


def _moment_row(moments):
    from app.models.seed import BaseScores, ScenarioRow, ScenarioStrategy, Tier

    return ScenarioRow(
        chapter="school",
        activity_code="x",
        activity_name="X",
        base_scores=BaseScores(temporal=1, sensory=1, logistical=1, human=1),
        stated_total=4,
        tier=Tier.FULL,
        rationale="r",
        strategies=[ScenarioStrategy(rank=1, title="t", body="b")],
        moments=moments,
    )


def test_seed_rejects_a_moment_loading_an_unknown_tag():
    from app.models.seed import ScenarioMoment
    from app.seed.loader import SeedValidationError, _validate_moments

    row = _moment_row([ScenarioMoment(id="m", label="M", loads=["ZZ-FAKE"])])
    with pytest.raises(SeedValidationError, match="unknown tag code"):
        _validate_moments(row)


def test_seed_rejects_duplicate_moment_ids():
    from app.models.seed import ScenarioMoment
    from app.seed.loader import SeedValidationError, _validate_moments

    row = _moment_row(
        [
            ScenarioMoment(id="dup", label="One", loads=["SN-NOISE"]),
            ScenarioMoment(id="dup", label="Two", loads=["SN-CROWD"]),
        ]
    )
    with pytest.raises(SeedValidationError, match="duplicate moment id"):
        _validate_moments(row)


# ---------------------------------------------------------------------------
# SERVICE: prepare_plan runs the Fusion Layer end to end (the enrichment loop)
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# The seeded social birthday party has moments: arrival [SN-CROWD, SN-NOISE, SN-UNPRED],
# games [SN-UNPRED, TR-SWITCH], food_and_cake [SN-TASTE, SN-SMELL, SN-NOISE], goodbye
# [TR-END, RC-MOD]. Used for the service-level fusion + gate + enrichment path.
BIRTHDAY = ("social", "birthday-party-small-familiar-children")


def _child_row(tags):
    return {
        "id": "c-1",
        "user_id": "u-1",
        "name": "Sam",
        "age_band": "6-8",
        "support_level_code": "SL-MED",
        "tags": list(tags),
        "created_at": NOW,
        "updated_at": NOW,
    }


def _fake_client(child_tags):
    """A FakeClient scripting the child read, the dedup miss, the insert, and a tag update.

    strategy_library_item reads/writes are deliberately UNSCRIPTED: the strategy service is
    fail-open, so a missing script (the fake raises) is swallowed, leaving the engine's own
    output, which is what these fusion tests assert.
    """
    return FakeClient(
        {
            ("child_profile", "select"): FakeResponse([_child_row(child_tags)]),
            ("child_profile", "update"): FakeResponse([_child_row(child_tags)]),
            ("activity_record", "select"): FakeResponse([]),
            ("activity_record", "insert"): FakeResponse([{"id": "act-1"}]),
        }
    )


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)


def test_prepare_plan_complete_when_tags_situate_two_moments(monkeypatch):
    # A child whose tags load two distinct moments (SN-CROWD -> arrival, SN-TASTE ->
    # food_and_cake) gets a COMPLETE plan: two situated strategies, gate passes, no
    # enrichment. Situated strategies surface FIRST and carry provenance.
    _patch_client(monkeypatch, _fake_client(["SN-CROWD", "SN-TASTE"]))
    plan = plans_service.prepare_plan(
        AUTHED,
        chapter=BIRTHDAY[0],
        activity_code=BIRTHDAY[1],
        today_flags=[],
        now=NOW,
    )
    assert plan.specificity.complete is True
    assert plan.specificity.profile_derived == 2
    assert plan.specificity.situated == 2
    assert plan.enrichment is None
    assert plan.getting_to_know is False
    # Situated strategies come first and are moment-labelled with situated_fusion provenance.
    assert plan.strategies[0].source == "situated_fusion"
    assert plan.strategies[0].moment in {"arrival", "food_and_cake"}
    assert plan.strategies[0].derived_from  # non-empty
    # The base scenario strategies still follow, with scenario_base provenance.
    assert any(s.source == "scenario_base" for s in plan.strategies)


def test_prepare_plan_incomplete_returns_one_enrichment_question(monkeypatch):
    # A child with NO tags: the gate fails and the plan carries the one value-first
    # enrichment question (highest-loading unconfirmed dimension = sensory), not generic.
    _patch_client(monkeypatch, _fake_client([]))
    plan = plans_service.prepare_plan(
        AUTHED,
        chapter=BIRTHDAY[0],
        activity_code=BIRTHDAY[1],
        today_flags=[],
        now=NOW,
    )
    assert plan.specificity.complete is False
    assert plan.getting_to_know is False
    assert plan.enrichment is not None
    assert plan.enrichment.dimension == "sensory"
    assert plan.enrichment.question.strip()
    assert plan.enrichment.options  # tap options with code + label
    assert all(opt.code and opt.label for opt in plan.enrichment.options)


def test_prepare_plan_enrichment_answer_persists_tags_and_completes(monkeypatch):
    # The enrichment loop: passing enrichment_answer PERSISTS the tags on the recipient
    # (a child_profile update is recorded) and re-runs scoring + fusion + gate in the SAME
    # call; tags spanning two moments make the plan complete.
    fake = _fake_client([])  # the child starts with no tags
    _patch_client(monkeypatch, fake)
    plan = plans_service.prepare_plan(
        AUTHED,
        chapter=BIRTHDAY[0],
        activity_code=BIRTHDAY[1],
        today_flags=[],
        now=NOW,
        enrichment_answer=["SN-CROWD", "SN-TASTE"],
    )
    assert plan.specificity.complete is True
    assert plan.enrichment is None
    assert plan.getting_to_know is False
    # The tapped tags were persisted as permanent tags (a child_profile UPDATE happened).
    tag_updates = [
        c
        for c in fake.calls
        if c["table"] == "child_profile" and c["op"] == "update"
    ]
    assert tag_updates, "enrichment tags must be persisted via a child_profile update"
    assert set(tag_updates[0]["payload"]["tags"]) >= {"SN-CROWD", "SN-TASTE"}


def test_prepare_plan_enrichment_answer_hitting_one_moment_gets_getting_to_know(monkeypatch):
    # SN-NOISE loads arrival AND food_and_cake for the birthday party, but SN-SMELL loads
    # only food_and_cake. Answering with a single-moment-only set after an enrichment leaves
    # the plan incomplete, so it returns the honest getting_to_know state, no new question.
    _patch_client(monkeypatch, _fake_client([]))
    plan = plans_service.prepare_plan(
        AUTHED,
        chapter=BIRTHDAY[0],
        activity_code=BIRTHDAY[1],
        today_flags=[],
        now=NOW,
        enrichment_answer=["SN-SMELL"],  # loads only food_and_cake => 1 situated
    )
    assert plan.specificity.complete is False
    assert plan.getting_to_know is True
    assert plan.enrichment is None  # exhausted: one enrichment already tried
