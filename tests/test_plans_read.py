"""No-DB tests for the v3 stored-plan READ endpoints (list + view).

The two reads return STORED values and never re-run the engine: GET /api/v3/plans
lists the caller's activity_records as summaries (newest first, optional ?chapter=),
and GET /api/v3/plans/{activity_id} returns one stored plan in the PreparationPlan
shape. Two layers, both off a live Supabase (blocked in the sandbox; the task
requires mocking):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is
    overridden for the authed cases (left real for the 401 cases), and the plans
    service reads are monkeypatched, so the parse -> validate -> call-service ->
    serialize path and the 401/422/404 contract are what is tested.

  - SERVICE (a fake Supabase client): get_anon_client is patched with a FakeClient so
    the real reads run over scripted activity_record / pulse_record rows. This pins
    that the list is newest-first, filters by chapter, carries the right pulse status,
    that the view reconstructs the full stored plan WITHOUT re-running the engine
    (dimension_explanations is null), and that a non-owned id is not found (404). The
    reads are user-scoped: every query filters by user_id (the activity_id lookup
    matches nothing for a forged id under RLS).

It also pins the exact PlanSummary shape the app consumes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.routes.plans as plans_routes
import app.services.plans as plans_service
from app.auth import AuthedUser, get_current_user
from app.models.plan import PlanStrategy, PlanSummary
from app.models.seed import Tier
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# A full stored activity_record row (every column the view reconstruction reads).
STORED_PLAN_ROW = {
    "id": "act-1",
    "chapter": "travel",
    "activity_code": "airport-departure-standard",
    "activity_name": "Airport departure: standard",
    "temporal": 5,
    "sensory": 5,
    "logistical": 5,
    "human": 4,
    "total": 19,
    "tier": "Pivot",
    "strategies": [
        {
            "title": "Lanyard",
            "detail": "Request hidden disability lanyard",
            "also_worked_in_chapter": None,
        },
        {
            "title": "Quiet route",
            "detail": "Ask staff for the quiet security lane",
            "also_worked_in_chapter": "social",
        },
    ],
    "scheduled_pulse_at": "2026-06-12T09:00:00+00:00",
}

# Three summary rows for the list (two travel, one social), with distinct created_at
# and scheduled_pulse_at so newest-first ordering and pulse-due are observable.
SUMMARY_ROWS = [
    {
        "id": "act-old-travel",
        "chapter": "travel",
        "activity_name": "Airport departure: standard",
        "tier": "Pivot",
        "total": 19,
        "scheduled_pulse_at": "2026-06-10T09:00:00+00:00",  # past => due (no pulse)
        "created_at": "2026-06-10T09:00:00+00:00",
    },
    {
        "id": "act-new-travel",
        "chapter": "travel",
        "activity_name": "Train journey: short",
        "tier": "Modified",
        "total": 11,
        "scheduled_pulse_at": "2026-06-20T09:00:00+00:00",  # future => not due
        "created_at": "2026-06-11T09:00:00+00:00",
    },
    {
        "id": "act-social",
        "chapter": "social",
        "activity_name": "Birthday party",
        "tier": "Full",
        "total": 7,
        "scheduled_pulse_at": "2026-06-09T09:00:00+00:00",  # past, BUT pulsed below
        "created_at": "2026-06-09T09:00:00+00:00",
    },
]


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required (401)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v3/plans",
        "/api/v3/plans/act-1",
    ],
)
def test_plan_read_routes_require_authentication(client, path):
    response = client.get(path)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /plans route wiring (service monkeypatched)
# ---------------------------------------------------------------------------

SAMPLE_SUMMARY = PlanSummary(
    activity_id="act-1",
    chapter="travel",
    activity_name="Airport departure: standard",
    tier=Tier.PIVOT,
    total=19,
    created_at=NOW,
    pulse_exists=False,
    pulse_due=True,
)


def test_list_plans_returns_the_summary_shape(authed, monkeypatch):
    monkeypatch.setattr(
        plans_routes.plans_service,
        "list_stored_plans",
        lambda user, **kwargs: [SAMPLE_SUMMARY],
    )
    response = authed.get("/api/v3/plans")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    item = body[0]
    # The exact PlanSummary contract the app consumes.
    assert set(item.keys()) == {
        "activity_id",
        "chapter",
        "activity_name",
        "tier",
        "total",
        "created_at",
        "pulse_exists",
        "pulse_due",
    }
    assert item["activity_id"] == "act-1"
    assert item["tier"] == "Pivot"
    assert item["total"] == 19
    assert item["pulse_exists"] is False
    assert item["pulse_due"] is True


def test_list_plans_passes_the_chapter_filter_to_the_service(authed, monkeypatch):
    captured = {}

    def _capture(user, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(plans_routes.plans_service, "list_stored_plans", _capture)
    response = authed.get("/api/v3/plans?chapter=travel")
    assert response.status_code == 200
    assert captured.get("chapter") == "travel"


def test_list_plans_without_a_chapter_filters_nothing(authed, monkeypatch):
    captured = {}

    def _capture(user, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(plans_routes.plans_service, "list_stored_plans", _capture)
    response = authed.get("/api/v3/plans")
    assert response.status_code == 200
    assert captured.get("chapter") is None


def test_list_plans_rejects_an_unknown_chapter_422(authed):
    response = authed.get("/api/v3/plans?chapter=not-a-chapter")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /plans/{activity_id} route wiring (service monkeypatched)
# ---------------------------------------------------------------------------


def test_get_plan_unknown_or_not_owned_is_404(authed, monkeypatch):
    def _raise(user, activity_id):
        raise plans_service.PlanNotFoundError("nope")

    monkeypatch.setattr(plans_routes.plans_service, "get_stored_plan", _raise)
    response = authed.get("/api/v3/plans/ghost")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# SERVICE: list_stored_plans reads the rows, newest first, with pulse status
# ---------------------------------------------------------------------------


def _list_fake(*, pulsed_ids):
    """A FakeClient scripting the activity_record list read + the pulse_record id read."""
    pulse_rows = [{"activity_id": aid} for aid in pulsed_ids]
    return FakeClient(
        {
            ("activity_record", "select"): FakeResponse(list(SUMMARY_ROWS)),
            ("pulse_record", "select"): FakeResponse(pulse_rows),
        }
    )


def test_list_stored_plans_newest_first_with_pulse_status(monkeypatch):
    # act-social has a pulse (pulse_exists, not due); the two travel plans have none.
    fake = _list_fake(pulsed_ids=["act-social"])
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)

    summaries = plans_service.list_stored_plans(AUTHED, now=NOW)

    # Newest created_at first: new-travel (06-11), old-travel (06-10), social (06-09).
    assert [s.activity_id for s in summaries] == [
        "act-new-travel",
        "act-old-travel",
        "act-social",
    ]
    by_id = {s.activity_id: s for s in summaries}

    # old-travel: no pulse, scheduled time in the past => due.
    assert by_id["act-old-travel"].pulse_exists is False
    assert by_id["act-old-travel"].pulse_due is True
    # new-travel: no pulse, scheduled time in the future => not due.
    assert by_id["act-new-travel"].pulse_exists is False
    assert by_id["act-new-travel"].pulse_due is False
    # social: pulse exists => pulse_exists true, never due (already answered).
    assert by_id["act-social"].pulse_exists is True
    assert by_id["act-social"].pulse_due is False

    # The stored score is carried verbatim (no engine run).
    assert by_id["act-new-travel"].tier == Tier.MODIFIED
    assert by_id["act-new-travel"].total == 11


def test_list_stored_plans_is_user_scoped(monkeypatch):
    # Every query the list issues must filter by the caller's user_id.
    fake = _list_fake(pulsed_ids=[])
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)

    plans_service.list_stored_plans(AUTHED, now=NOW)

    activity_selects = [
        c for c in fake.calls if c["table"] == "activity_record" and c["op"] == "select"
    ]
    pulse_selects = [
        c for c in fake.calls if c["table"] == "pulse_record" and c["op"] == "select"
    ]
    assert activity_selects and pulse_selects
    for call in activity_selects + pulse_selects:
        assert ("user_id", "u-1") in call["filters"]


def test_list_stored_plans_chapter_filter_is_applied(monkeypatch):
    fake = _list_fake(pulsed_ids=[])
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)

    plans_service.list_stored_plans(AUTHED, chapter="travel", now=NOW)

    activity_select = next(
        c for c in fake.calls if c["table"] == "activity_record" and c["op"] == "select"
    )
    # The chapter filter is pushed down to the query alongside the user_id scope.
    assert ("chapter", "travel") in activity_select["filters"]
    assert ("user_id", "u-1") in activity_select["filters"]


# ---------------------------------------------------------------------------
# SERVICE: get_stored_plan reconstructs the full plan WITHOUT re-running the engine
# ---------------------------------------------------------------------------


def test_get_stored_plan_returns_the_full_stored_plan(monkeypatch):
    fake = FakeClient({("activity_record", "select"): FakeResponse([STORED_PLAN_ROW])})
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)

    plan = plans_service.get_stored_plan(AUTHED, "act-1")

    # The stored values are returned verbatim (no engine run).
    assert plan.activity_id == "act-1"
    assert plan.chapter == "travel"
    assert plan.activity_code == "airport-departure-standard"
    assert plan.scores.temporal == 5
    assert plan.scores.sensory == 5
    assert plan.scores.logistical == 5
    assert plan.scores.human == 4
    assert plan.total == 19
    assert plan.tier == Tier.PIVOT
    assert plan.scheduled_pulse_at.isoformat() == "2026-06-12T09:00:00+00:00"

    # The stored strategies come back in order, with the cross-context label preserved.
    assert [s.title for s in plan.strategies] == ["Lanyard", "Quiet route"]
    assert isinstance(plan.strategies[0], PlanStrategy)
    assert plan.strategies[0].also_worked_in_chapter is None
    assert plan.strategies[1].also_worked_in_chapter == "social"

    # The engine was NOT re-run: dimension_explanations is null on a stored read, and
    # used_chapter_average stays at its default (a POST-time estimate flag, not stored).
    assert plan.dimension_explanations is None
    assert plan.used_chapter_average is False


def test_get_stored_plan_not_owned_raises(monkeypatch):
    # RLS scopes the read to the caller, so a forged id matches nothing => not found.
    fake = FakeClient({("activity_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)
    with pytest.raises(plans_service.PlanNotFoundError):
        plans_service.get_stored_plan(AUTHED, "someone-elses-id")


def test_get_stored_plan_lookup_is_user_scoped(monkeypatch):
    fake = FakeClient({("activity_record", "select"): FakeResponse([STORED_PLAN_ROW])})
    monkeypatch.setattr("app.services.plans.get_anon_client", lambda token=None: fake)

    plans_service.get_stored_plan(AUTHED, "act-1")

    select = next(
        c for c in fake.calls if c["table"] == "activity_record" and c["op"] == "select"
    )
    # The lookup filters by BOTH the activity id and the caller's user_id (the first
    # line of scoping; RLS is the backstop).
    assert ("id", "act-1") in select["filters"]
    assert ("user_id", "u-1") in select["filters"]
