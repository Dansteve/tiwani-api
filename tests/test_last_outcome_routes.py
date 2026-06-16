"""No-DB tests for the "What helped last time" endpoint (ProductReview.md item 5).

Route wiring only (TestClient against main.app): the current-user dependency is overridden for
the authed cases (left real for the 401 case, which short-circuits on a missing token), and the
last_outcome service is monkeypatched, so the route's parse -> validate -> call-service ->
serialize path and the 401 / 404 / null-body contract are what is tested. The service behaviour
(the §4.10 / §4.8 stored-fact reads) is proven in test_last_outcome_service.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.routes.chapters as chapters_routes
from app.auth import AuthedUser, get_current_user
from app.models.last_outcome import LastOutcome

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

SAMPLE = LastOutcome(
    chapter="school",
    activity_name="Assembly",
    outcome_code="okay",
    tier_recommended="Pivot",
    challenge_dimension="sensory",
    worked_strategy="Arrive early",
    pivot_helped=True,
    recorded_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
)


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


def test_requires_authentication(client):
    assert client.get("/api/v1/chapters/school/last-outcome").status_code == 401


def test_returns_the_recall(authed, monkeypatch):
    captured = {}

    def _get(user, *, chapter, child_id=None):
        captured["chapter"] = chapter
        captured["child_id"] = child_id
        return SAMPLE

    monkeypatch.setattr(chapters_routes.last_outcome_service, "get_last_outcome", _get)
    response = authed.get("/api/v1/chapters/school/last-outcome")
    assert response.status_code == 200
    body = response.json()
    assert captured["chapter"] == "school"
    assert set(body.keys()) == {
        "chapter",
        "activity_name",
        "outcome_code",
        "tier_recommended",
        "challenge_dimension",
        "worked_strategy",
        "pivot_helped",
        "recorded_at",
    }
    assert body["outcome_code"] == "okay"
    assert body["tier_recommended"] == "Pivot"
    assert body["worked_strategy"] == "Arrive early"
    assert body["pivot_helped"] is True


def test_first_time_chapter_returns_null_body(authed, monkeypatch):
    monkeypatch.setattr(
        chapters_routes.last_outcome_service,
        "get_last_outcome",
        lambda user, *, chapter, child_id=None: None,
    )
    response = authed.get("/api/v1/chapters/travel/last-outcome")
    assert response.status_code == 200
    assert response.json() is None


def test_child_id_is_threaded(authed, monkeypatch):
    captured = {}

    def _get(user, *, chapter, child_id=None):
        captured["child_id"] = child_id
        return None

    monkeypatch.setattr(chapters_routes.last_outcome_service, "get_last_outcome", _get)
    authed.get("/api/v1/chapters/school/last-outcome?child_id=ch-9")
    assert captured["child_id"] == "ch-9"


def test_unknown_chapter_is_404(authed):
    # The chapter is validated against the six fixed codes before the service is reached.
    response = authed.get("/api/v1/chapters/not-a-chapter/last-outcome")
    assert response.status_code == 404


def test_unowned_child_id_is_404(authed, monkeypatch):
    from app.services.profile import ChildNotFoundError

    def _raise(user, *, chapter, child_id=None):
        raise ChildNotFoundError("No care recipient found for this id")

    monkeypatch.setattr(chapters_routes.last_outcome_service, "get_last_outcome", _raise)
    response = authed.get("/api/v1/chapters/school/last-outcome?child_id=not-mine")
    assert response.status_code == 404
