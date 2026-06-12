"""No-DB tests for the v3 Strategy Library endpoints (suppress / allow / dismiss-cross-context).

Route wiring only (TestClient against main.app): the current-user dependency is overridden for
the authed cases (left real for the 401 cases, which short-circuit on a missing token), and the
strategies service is monkeypatched, so the route's parse -> validate -> call-service ->
serialize path and the 401 / 404 / 422 error contract are what is tested. The service behaviour
(the section 4.10 rules) is proven in test_strategies_service.py.
"""

from __future__ import annotations

import pytest

import app.routes.strategies as strategies_routes
from app.auth import AuthedUser, get_current_user
from app.models.strategy import StrategyItemView

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

SAMPLE_VIEW = StrategyItemView(
    library_item_id="lib-1",
    chapter="travel",
    scenario_type="airport",
    title="Lanyard",
    suppressed=True,
    promoted=False,
    removal_count=3,
    positive_count=0,
    negative_count=0,
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
    "path",
    [
        "/api/v1/strategies/lib-1/suppress",
        "/api/v1/strategies/lib-1/allow",
        "/api/v1/strategies/lib-1/dismiss-cross-context?chapter=travel",
    ],
)
def test_strategy_routes_require_authentication(client, path):
    assert client.post(path).status_code == 401


# ---------------------------------------------------------------------------
# suppress
# ---------------------------------------------------------------------------


def test_suppress_returns_the_updated_item(authed, monkeypatch):
    captured = {}

    def _remove(user, library_item_id):
        captured["id"] = library_item_id
        return SAMPLE_VIEW

    monkeypatch.setattr(strategies_routes.strategy_library, "remove_strategy", _remove)
    response = authed.post("/api/v1/strategies/lib-1/suppress")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "library_item_id",
        "chapter",
        "scenario_type",
        "title",
        "suppressed",
        "promoted",
        "removal_count",
        "positive_count",
        "negative_count",
    }
    assert body["suppressed"] is True
    assert captured["id"] == "lib-1"


def test_suppress_unknown_item_is_404(authed, monkeypatch):
    def _raise(user, library_item_id):
        raise strategies_routes.strategy_library.StrategyItemNotFoundError("nope")

    monkeypatch.setattr(strategies_routes.strategy_library, "remove_strategy", _raise)
    assert authed.post("/api/v1/strategies/nope/suppress").status_code == 404


# ---------------------------------------------------------------------------
# allow (re-allow)
# ---------------------------------------------------------------------------


def test_allow_returns_the_updated_item(authed, monkeypatch):
    allowed = SAMPLE_VIEW.model_copy(update={"suppressed": False, "removal_count": 0})
    monkeypatch.setattr(
        strategies_routes.strategy_library, "allow_strategy", lambda user, library_item_id: allowed
    )
    response = authed.post("/api/v1/strategies/lib-1/allow")
    assert response.status_code == 200
    assert response.json()["suppressed"] is False
    assert response.json()["removal_count"] == 0


def test_allow_unknown_item_is_404(authed, monkeypatch):
    def _raise(user, library_item_id):
        raise strategies_routes.strategy_library.StrategyItemNotFoundError("nope")

    monkeypatch.setattr(strategies_routes.strategy_library, "allow_strategy", _raise)
    assert authed.post("/api/v1/strategies/nope/allow").status_code == 404


# ---------------------------------------------------------------------------
# dismiss-cross-context
# ---------------------------------------------------------------------------


def test_dismiss_cross_context_forwards_chapter(authed, monkeypatch):
    captured = {}

    def _dismiss(user, library_item_id, chapter):
        captured["id"] = library_item_id
        captured["chapter"] = chapter
        return SAMPLE_VIEW

    monkeypatch.setattr(strategies_routes.strategy_library, "dismiss_cross_context", _dismiss)
    response = authed.post("/api/v1/strategies/lib-1/dismiss-cross-context?chapter=social")
    assert response.status_code == 200
    assert captured == {"id": "lib-1", "chapter": "social"}


def test_dismiss_cross_context_unknown_chapter_is_422(authed):
    # An unknown chapter code fails the Chapter query validation before the service is reached.
    assert (
        authed.post("/api/v1/strategies/lib-1/dismiss-cross-context?chapter=not-a-chapter").status_code
        == 422
    )


def test_dismiss_cross_context_missing_chapter_is_422(authed):
    # chapter is a required query param.
    assert authed.post("/api/v1/strategies/lib-1/dismiss-cross-context").status_code == 422
