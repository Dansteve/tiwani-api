"""The FUSION_ENABLED server gate over the plan response (FusionBuildIssues.md G2).

The Fusion Layer output (situated strategies, the Specificity Gate, the enrichment question)
is care-adjacent governed copy, gated on the psychiatrist sign-off. The api mirrors the app's
NEXT_PUBLIC_FUSION_ENABLED with a server flag (app/engines/lce/flag.py), OFF by default. These
tests pin the OFF-vs-ON contract of the plan response:

  - OFF (the default): the plan is EXACTLY pre-fusion. The ranked strategy list is the base
    scenario/cross-context list (no situated strategies), specificity is null, enrichment is
    null, getting_to_know is false, and any enrichment_answer is IGNORED (no tags persisted,
    no re-run). The stored-plan READ likewise drops the situated (governed) strategies and
    omits the gate.
  - ON: the full Fusion output is returned (today's behaviour).
  - Either way, the section 4.4 SCORING (scores / total / tier) is IDENTICAL: the flag gates
    only what the response EXPOSES, never a number.

No live Supabase (mocked with a fake client); the flag is toggled via monkeypatch, the
analogue of the checkin/context flag tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.services.plans as plans_service
from app.auth import AuthedUser
from app.engines.lce.flag import FUSION_FLAG_ENV, is_fusion_enabled
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# The seeded birthday party has moments; SN-CROWD loads `arrival` and SN-TASTE loads
# `food_and_cake`, so this tag set situates TWO moments -> a COMPLETE gate when fusion is ON.
BIRTHDAY = ("social", "birthday-party-small-familiar-children")
SITUATING_TAGS = ["SN-CROWD", "SN-TASTE"]


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

    strategy_library_item reads/writes are deliberately UNSCRIPTED (the strategy service is
    fail-open), leaving the engine's own strategy output, which is what these tests assert.
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


def _prepare(**kwargs):
    return plans_service.prepare_plan(
        AUTHED, chapter=BIRTHDAY[0], activity_code=BIRTHDAY[1], today_flags=[], now=NOW, **kwargs
    )


# ---------------------------------------------------------------------------
# the flag itself (the truthiness table, mirroring the checkin/context gate)
# ---------------------------------------------------------------------------


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv(FUSION_FLAG_ENV, raising=False)
    assert is_fusion_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "On"])
def test_flag_on_for_truthy_values(monkeypatch, value):
    monkeypatch.setenv(FUSION_FLAG_ENV, value)
    assert is_fusion_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "off", "", "no", "  "])
def test_flag_off_for_non_truthy_values(monkeypatch, value):
    monkeypatch.setenv(FUSION_FLAG_ENV, value)
    assert is_fusion_enabled() is False


# ---------------------------------------------------------------------------
# POST /plans (prepare_plan): OFF omits the fusion output, ON returns it
# ---------------------------------------------------------------------------


def test_prepare_plan_off_omits_fusion(monkeypatch):
    # Default OFF: even with tags that WOULD situate two moments, the plan is pre-fusion.
    monkeypatch.delenv(FUSION_FLAG_ENV, raising=False)
    _patch_client(monkeypatch, _fake_client(SITUATING_TAGS))
    plan = _prepare()

    assert plan.specificity is None
    assert plan.enrichment is None
    assert plan.getting_to_know is False
    # No situated strategies at all; the base ranked list is still present.
    assert plan.strategies
    assert all(s.source != "situated_fusion" for s in plan.strategies)
    assert all(not s.moment for s in plan.strategies)


def test_prepare_plan_off_ignores_enrichment_answer(monkeypatch):
    # enrichment_answer is IGNORED while OFF: no tags are persisted (no child_profile update)
    # and the plan stays pre-fusion. The route still validates the codes; the service no-ops.
    monkeypatch.delenv(FUSION_FLAG_ENV, raising=False)
    fake = _fake_client([])  # the child starts with no tags
    _patch_client(monkeypatch, fake)
    plan = _prepare(enrichment_answer=SITUATING_TAGS)

    assert plan.specificity is None
    assert plan.enrichment is None
    tag_updates = [
        c for c in fake.calls if c["table"] == "child_profile" and c["op"] == "update"
    ]
    assert tag_updates == [], "enrichment_answer must not persist tags while fusion is OFF"


def test_prepare_plan_on_returns_full_fusion(monkeypatch):
    # ON: the full Fusion output. Tags that situate two moments give a COMPLETE plan with the
    # situated strategies surfaced first and carrying provenance.
    monkeypatch.setenv(FUSION_FLAG_ENV, "true")
    _patch_client(monkeypatch, _fake_client(SITUATING_TAGS))
    plan = _prepare()

    assert plan.specificity is not None
    assert plan.specificity.complete is True
    assert plan.specificity.situated == 2
    assert plan.enrichment is None
    assert plan.getting_to_know is False
    assert plan.strategies[0].source == "situated_fusion"
    assert plan.strategies[0].derived_from  # non-empty loaders


def test_flag_gates_the_response_not_the_scores(monkeypatch):
    # The flag gates ONLY what the response exposes; the section 4.4 numbers are identical.
    monkeypatch.delenv(FUSION_FLAG_ENV, raising=False)
    _patch_client(monkeypatch, _fake_client(SITUATING_TAGS))
    off = _prepare()

    monkeypatch.setenv(FUSION_FLAG_ENV, "true")
    _patch_client(monkeypatch, _fake_client(SITUATING_TAGS))
    on = _prepare()

    assert off.total == on.total
    assert off.tier == on.tier
    assert (off.scores.temporal, off.scores.sensory, off.scores.logistical, off.scores.human) == (
        on.scores.temporal,
        on.scores.sensory,
        on.scores.logistical,
        on.scores.human,
    )
    # And the flag genuinely changed the exposed fusion fields.
    assert off.specificity is None and on.specificity is not None


# ---------------------------------------------------------------------------
# GET /plans/{id} (get_stored_plan): OFF drops the situated copy + omits the gate
# ---------------------------------------------------------------------------

# A stored activity_record whose jsonb strategies carry two situated (governed) strategies
# plus one base strategy (as a plan prepared while the flag was ON would have stored).
STORED_ROW_WITH_SITUATED = {
    "id": "act-1",
    "chapter": "social",
    "activity_code": "birthday-party-small-familiar-children",
    "activity_name": "Birthday party",
    "temporal": 3,
    "sensory": 4,
    "logistical": 3,
    "human": 4,
    "total": 14,
    "tier": "Pivot",
    "strategies": [
        {
            "title": "Arrival / playground",
            "detail": "A situated sentence for arrival.",
            "source": "situated_fusion",
            "derived_from": ["SN-CROWD"],
            "moment": "arrival",
            "moment_label": "Arrival / playground",
            "also_worked_in_chapter": None,
        },
        {
            "title": "Food and cake",
            "detail": "A situated sentence for food and cake.",
            "source": "situated_fusion",
            "derived_from": ["SN-TASTE"],
            "moment": "food_and_cake",
            "moment_label": "Food and cake",
            "also_worked_in_chapter": None,
        },
        {
            "title": "Bring a familiar comfort item",
            "detail": "A base scenario strategy.",
            "source": "scenario_base",
            "derived_from": [],
            "moment": None,
            "moment_label": None,
            "also_worked_in_chapter": None,
        },
    ],
    "scheduled_pulse_at": "2026-06-12T09:00:00+00:00",
}


def _stored_read_fake():
    return FakeClient(
        {("activity_record", "select"): FakeResponse([STORED_ROW_WITH_SITUATED])}
    )


def test_get_stored_plan_on_keeps_situated_and_recomputes_gate(monkeypatch):
    monkeypatch.setenv(FUSION_FLAG_ENV, "true")
    monkeypatch.setattr(
        "app.services.plans.get_anon_client", lambda token=None: _stored_read_fake()
    )
    plan = plans_service.get_stored_plan(AUTHED, "act-1")

    assert plan.specificity is not None
    assert plan.specificity.situated == 2
    assert plan.specificity.complete is True
    situated = [s for s in plan.strategies if s.source == "situated_fusion"]
    assert len(situated) == 2


def test_get_stored_plan_off_drops_situated_and_omits_gate(monkeypatch):
    monkeypatch.delenv(FUSION_FLAG_ENV, raising=False)
    monkeypatch.setattr(
        "app.services.plans.get_anon_client", lambda token=None: _stored_read_fake()
    )
    plan = plans_service.get_stored_plan(AUTHED, "act-1")

    # The gate is omitted and the governed situated strategies never surface; only the base
    # strategy remains, so the stored read is exactly pre-fusion.
    assert plan.specificity is None
    assert all(s.source != "situated_fusion" for s in plan.strategies)
    assert [s.title for s in plan.strategies] == ["Bring a familiar comfort item"]
    # The stored scores are still returned verbatim (never gated).
    assert plan.total == 14
    assert plan.tier == "Pivot"
