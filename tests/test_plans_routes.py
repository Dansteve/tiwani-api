"""No-DB tests for the v3 Preparation Plan endpoints (the LCE) and the dashboard wiring.

Two layers, both off a live Supabase (blocked in the sandbox; the task requires
mocking):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is
    overridden for the authed cases (left real for the 401 cases, which
    short-circuit on a missing token), and the plans service is monkeypatched, so
    the route's parse -> validate -> call-service -> serialize path and the
    401/422/409 error contract are what is tested.

  - SERVICE + dashboard (the real engine, a fake Supabase client): get_anon_client
    is patched with the FakeClient so the REAL engine runs, the activity_record
    INSERT is recorded, and the chapters service then reads that recorded row back
    and returns the real activity_count / last_prepared_at. This pins the section
    4.4 step 8 write AND that the Task 4 dashboard is now live (it no longer returns
    0 for a chapter the user has prepared in).

It also pins the exact PreparationPlan shape the app mirrors.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.routes.plans as plans_routes
import app.services.chapters as chapters_service
import app.services.plans as plans_service
from app.auth import AuthedUser, get_current_user
from app.models.plan import (
    DimensionExplanations,
    DimensionScores,
    PlanStrategy,
    PreparationPlan,
)
from app.models.seed import Tier
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

CHILD_ROW = {
    "id": "c-1",
    "user_id": "u-1",
    "name": "Sam",
    "age_band": "6-8",
    "support_level_code": "SL-MED",
    "tags": ["SN-NOISE", "CM-MIXED"],
    "created_at": NOW,
    "updated_at": NOW,
}

SAMPLE_PLAN = PreparationPlan(
    activity_id="a-1",
    chapter="travel",
    activity_code="airport-departure-standard",
    activity_name="Airport departure: standard",
    scores=DimensionScores(temporal=5, sensory=5, logistical=5, human=4),
    total=19,
    tier=Tier.PIVOT,
    strategies=[PlanStrategy(title="Lanyard", detail="Request hidden disability lanyard")],
    dimension_explanations=DimensionExplanations(
        temporal="This temporal pressure is high (the timing).",
        sensory="This sensory pressure is high (the noise).",
        logistical="This logistical pressure is high (the steps).",
        human="This human pressure is high (the people).",
    ),
    scheduled_pulse_at=NOW,
    used_chapter_average=False,
)


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required (401)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v3/plans"),
        ("get", "/api/v3/chapters/travel/activities"),
    ],
)
def test_plan_routes_require_authentication(client, method, path):
    if method == "get":
        response = client.get(path)
    else:
        response = client.post(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /plans route wiring (service monkeypatched)
# ---------------------------------------------------------------------------


def test_create_plan_success_returns_the_plan_shape(authed, monkeypatch):
    monkeypatch.setattr(
        plans_routes.plans_service,
        "prepare_plan",
        lambda user, **kwargs: SAMPLE_PLAN,
    )
    response = authed.post(
        "/api/v3/plans",
        json={
            "chapter": "travel",
            "activity_code": "airport-departure-standard",
            "today_flags": ["TG-ILL"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    # The exact PreparationPlan contract the app mirrors.
    assert set(body.keys()) == {
        "activity_id",
        "chapter",
        "activity_code",
        "activity_name",
        "scores",
        "total",
        "tier",
        "strategies",
        "dimension_explanations",
        "scheduled_pulse_at",
        "used_chapter_average",
    }
    assert set(body["scores"].keys()) == {"temporal", "sensory", "logistical", "human"}
    assert set(body["dimension_explanations"].keys()) == {
        "temporal",
        "sensory",
        "logistical",
        "human",
    }
    assert body["tier"] == "Pivot"
    assert body["total"] == 19
    assert body["strategies"][0]["title"] == "Lanyard"


def test_create_plan_rejects_unknown_chapter_422(authed):
    response = authed.post(
        "/api/v3/plans",
        json={"chapter": "not-a-chapter", "activity_code": "x"},
    )
    assert response.status_code == 422


def test_create_plan_rejects_a_non_tg_today_flag_422(authed):
    # A permanent profile tag (SN-) is not a "today" flag; only TG- codes are valid.
    response = authed.post(
        "/api/v3/plans",
        json={
            "chapter": "travel",
            "activity_code": "airport-departure-standard",
            "today_flags": ["SN-NOISE"],
        },
    )
    assert response.status_code == 422


def test_create_plan_rejects_an_unknown_tag_code_422(authed):
    response = authed.post(
        "/api/v3/plans",
        json={
            "chapter": "travel",
            "activity_code": "airport-departure-standard",
            "today_flags": ["ZZ-NOPE"],
        },
    )
    assert response.status_code == 422


def test_create_plan_without_a_care_recipient_is_409(authed, monkeypatch):
    def _raise(user, **kwargs):
        raise plans_service.NoCareRecipientError("none")

    monkeypatch.setattr(plans_routes.plans_service, "prepare_plan", _raise)
    response = authed.post(
        "/api/v3/plans",
        json={"chapter": "travel", "activity_code": "airport-departure-standard"},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# GET /chapters/{chapter}/activities
# ---------------------------------------------------------------------------


def test_list_activities_returns_seeded_options(authed):
    response = authed.get("/api/v3/chapters/travel/activities")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) >= 1
    sample = body[0]
    assert set(sample.keys()) == {"activity_code", "activity_name", "tier"}
    assert sample["tier"] in {"Full", "Modified", "Pivot"}
    # Every returned activity is a real travel scenario the engine can score.
    codes = {o["activity_code"] for o in body}
    assert "airport-departure-standard" in codes


def test_list_activities_unknown_chapter_is_404(authed):
    response = authed.get("/api/v3/chapters/not-a-chapter/activities")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# SERVICE: prepare_plan runs the real engine, writes the record, returns the plan
# ---------------------------------------------------------------------------


def _fake_client_for_plan_write():
    """A FakeClient scripting the child read and the activity_record insert.

    get_child reads child_profile (select) -> the SL-MED Sam row; the activity
    insert returns the stored row with its id (the write-confirmed representation).
    """
    return FakeClient(
        {
            ("child_profile", "select"): FakeResponse([CHILD_ROW]),
            ("activity_record", "insert"): FakeResponse(
                [{"id": "act-123"}]
            ),
        }
    )


def test_prepare_plan_runs_engine_and_writes_record(monkeypatch):
    fake = _fake_client_for_plan_write()
    # Both the profile service (get_child) and the plans service insert go through
    # get_anon_client; patch both module references to the same fake client.
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)

    plan = plans_service.prepare_plan(
        AUTHED,
        chapter="travel",
        activity_code="airport-departure-standard",
        today_flags=["TG-ILL"],
        activity_date=None,
        now=NOW,
    )

    # The plan is for the stored record (write confirmed, section 4.4 step 8).
    assert plan.activity_id == "act-123"
    assert plan.chapter == "travel"
    assert plan.tier in {Tier.FULL, Tier.MODIFIED, Tier.PIVOT}

    # The engine actually ran: airport-standard base is 4/5/5/3, SL-MED x1.2 rounds
    # to 5/6->5/6->5/4 capped at 5 -> 5/5/5/4; SN-NOISE +1 Sensory (already 5);
    # TG-ILL +2 all caps at 5 -> 5/5/5/5 total 20 Pivot.
    assert plan.scores.temporal == 5
    assert plan.scores.sensory == 5
    assert plan.scores.logistical == 5
    assert plan.scores.human == 5
    assert plan.total == 20
    assert plan.tier == Tier.PIVOT

    # An activity_record INSERT was issued, scoped to the user and child, carrying
    # the final scores and the scheduled pulse time.
    inserts = [c for c in fake.calls if c["op"] == "insert" and c["table"] == "activity_record"]
    assert len(inserts) == 1
    payload = inserts[0]["payload"]
    assert payload["user_id"] == "u-1"
    assert payload["child_id"] == "c-1"
    assert payload["chapter"] == "travel"
    assert payload["total"] == 20
    assert payload["tier"] == "Pivot"
    assert payload["today_flags"] == ["TG-ILL"]
    assert isinstance(payload["strategies"], list)


def test_prepare_plan_schedules_pulse_for_activity_date_plus_two_hours():
    from datetime import date

    pulse = plans_service.compute_scheduled_pulse_at(date(2026, 6, 20), now=NOW)
    # Activity date anchored at 09:00 + 2h = 11:00 on the activity date.
    assert pulse.date().isoformat() == "2026-06-20"
    assert pulse.hour == 11
    assert pulse.minute == 0


def test_prepare_plan_schedules_pulse_at_0900_next_day_without_a_date():
    pulse = plans_service.compute_scheduled_pulse_at(None, now=NOW)
    # No activity date: 09:00 the day after now (2026-06-12).
    assert pulse.date().isoformat() == "2026-06-12"
    assert pulse.hour == 9
    assert pulse.minute == 0


def test_prepare_plan_without_a_care_recipient_raises(monkeypatch):
    fake = FakeClient({("child_profile", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)
    with pytest.raises(plans_service.NoCareRecipientError):
        plans_service.prepare_plan(
            AUTHED,
            chapter="travel",
            activity_code="airport-departure-standard",
            today_flags=[],
            now=NOW,
        )


# ---------------------------------------------------------------------------
# DASHBOARD WIRING: chapters now returns the real activity_count / last_prepared_at
# ---------------------------------------------------------------------------


def test_chapters_service_counts_activities_and_last_prepared(monkeypatch):
    # Three activity_record rows for the user: two in travel, one in social, with
    # different created_at timestamps. The chapters service must report count 2 for
    # travel (last_prepared = the later timestamp), count 1 for social, and 0 for
    # the rest (still the not-started baseline).
    rows = [
        {"chapter": "travel", "created_at": "2026-06-10T09:00:00+00:00"},
        {"chapter": "travel", "created_at": "2026-06-11T09:00:00+00:00"},
        {"chapter": "social", "created_at": "2026-06-09T09:00:00+00:00"},
    ]
    fake = FakeClient({("activity_record", "select"): FakeResponse(rows)})
    monkeypatch.setattr("app.services.chapters.get_anon_client", lambda token=None: fake)
    # Since Task 6, the dashboard also folds the user's pulses for the chapter LCI.
    # This case has activities but no pulses yet, so the LCI client returns none and
    # every chapter's lci stays null (a plan made, no Pulse yet, reads as no LCI).
    lci_fake = FakeClient({("pulse_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: lci_fake)
    # Since Task 7, the dashboard also reads the user's active alerts. No alert rows
    # here, so alert_level stays null on every chapter.
    alerts_fake = FakeClient({("alert_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: alerts_fake)

    statuses = chapters_service.list_chapter_statuses(AUTHED)
    by_chapter = {s.chapter: s for s in statuses}

    assert by_chapter["travel"].activity_count == 2
    assert by_chapter["travel"].last_prepared_at == "2026-06-11T09:00:00+00:00"
    assert by_chapter["social"].activity_count == 1
    assert by_chapter["social"].last_prepared_at == "2026-06-09T09:00:00+00:00"
    # The other chapters stay at the not-started baseline.
    assert by_chapter["school"].activity_count == 0
    assert by_chapter["school"].last_prepared_at is None
    # LCI is null with no pulse; alert level is null with no active alert.
    assert by_chapter["travel"].lci is None
    assert by_chapter["travel"].alert_level is None


def test_chapters_service_fresh_user_stays_all_not_started(monkeypatch):
    fake = FakeClient({("activity_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.chapters.get_anon_client", lambda token=None: fake)
    lci_fake = FakeClient({("pulse_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: lci_fake)
    alerts_fake = FakeClient({("alert_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: alerts_fake)
    statuses = chapters_service.list_chapter_statuses(AUTHED)
    assert len(statuses) == 6
    for s in statuses:
        assert s.activity_count == 0
        assert s.last_prepared_at is None
        assert s.alert_level is None
        assert s.lci is None
        assert s.alert_level is None
