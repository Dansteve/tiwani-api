"""Tests for the v1 calendar context endpoint (the display-only Real-World Context Layer).

The calendar context (FeatureDecisions.md 2026-06-19, Part B, the calendar slice) is a
READ-ONLY surface that returns public UK calendar windows the app overlays on the check-in
history. It reads NO user data (the calendar is public reference data) and touches NO score.
These tests run with no live Supabase (the route has no DB layer), against main.app via
TestClient.

What they pin:
  - AUTH: 401 without a bearer token.
  - THE SIGN-OFF GATE: 404 while the OFF-by-default flag is disabled (the surface does not
    exist for users until the psychiatrist copy sign-off enables CALENDAR_CONTEXT_ENABLED).
  - THE RESPONSE SHAPE + VERBATIM GOVERNED COPY when enabled: the {from_date, to_date, intro,
    hedge, windows, needs_signoff} shape, the intro / hedge matching the engine constants,
    and each window carrying its world-fact note + provenance + confidence.
  - DATE FILTERING: a from/to range returns only the overlapping public windows.
  - NO SCORE: the response carries no score / trajectory field (it never touches the LCI).
"""

from __future__ import annotations

import pytest

from app.auth import AuthedUser, get_current_user
from app.engines.context import CALENDAR_HEDGE, CALENDAR_INTRO
from app.engines.context.flag import CALENDAR_CONTEXT_FLAG_ENV

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

CALENDAR_PATH = "/api/v1/context/calendar"


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def enabled(monkeypatch):
    """Enable the OFF-by-default surface for the duration of a test (sign-off simulation)."""
    monkeypatch.setenv(CALENDAR_CONTEXT_FLAG_ENV, "true")
    yield


# ---------------------------------------------------------------------------
# auth required (401)
# ---------------------------------------------------------------------------


def test_calendar_requires_authentication(client, enabled):
    # Even with the surface enabled, no bearer token is a 401 (the current-user dependency).
    response = client.get(CALENDAR_PATH)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# the sign-off gate (404 while OFF by default)
# ---------------------------------------------------------------------------


def test_calendar_is_404_when_the_flag_is_off(authed, monkeypatch):
    # The flag is OFF by default: the surface does not exist for users. Authenticated, but
    # still a 404 (not a 403), so a probe cannot tell the route is there.
    monkeypatch.delenv(CALENDAR_CONTEXT_FLAG_ENV, raising=False)
    response = authed.get(CALENDAR_PATH)
    assert response.status_code == 404


@pytest.mark.parametrize("value", ["0", "false", "off", "", "no"])
def test_calendar_stays_404_for_non_truthy_flag_values(authed, monkeypatch, value):
    monkeypatch.setenv(CALENDAR_CONTEXT_FLAG_ENV, value)
    response = authed.get(CALENDAR_PATH)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# the response shape + verbatim governed copy (flag enabled)
# ---------------------------------------------------------------------------


def test_calendar_returns_the_governed_shape(authed, enabled):
    response = authed.get(CALENDAR_PATH, params={"from": "2025-01-01", "to": "2025-12-31"})
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {
        "from_date",
        "to_date",
        "intro",
        "hedge",
        "windows",
        "needs_signoff",
    }
    # The copy is the engine's GOVERNED text, verbatim (the app authors none).
    assert body["intro"] == CALENDAR_INTRO
    assert body["hedge"] == CALENDAR_HEDGE
    # A standing reminder this surface is sign-off gated.
    assert body["needs_signoff"] is True
    # Each window carries its world-fact note + provenance + qualitative confidence.
    assert body["windows"], "expected windows in 2025"
    first = body["windows"][0]
    assert set(first) == {
        "kind",
        "label",
        "start",
        "end",
        "division",
        "note",
        "source",
        "confidence",
    }
    assert first["confidence"] in {"confirmed", "approximate"}
    assert first["note"]


def test_calendar_filters_to_the_requested_range(authed, enabled):
    # July to August 2025 overlaps the summer holidays + the summer bank holiday, not
    # Christmas.
    response = authed.get(CALENDAR_PATH, params={"from": "2025-07-01", "to": "2025-08-31"})
    assert response.status_code == 200
    labels = [w["label"] for w in response.json()["windows"]]
    assert "Summer holidays" in labels
    assert "Summer bank holiday" in labels
    assert "Christmas holidays" not in labels


def test_calendar_carries_no_score_field(authed, enabled):
    # The context layer never touches the LCI: the response has no score / trajectory.
    response = authed.get(CALENDAR_PATH, params={"from": "2025-01-01", "to": "2025-12-31"})
    body = response.json()
    assert "score" not in body
    assert "trajectory" not in body
    for window in body["windows"]:
        assert "score" not in window


def test_calendar_rejects_an_unparseable_date(authed, enabled):
    # A malformed date is a 422 from the query validation (no silent fallback).
    response = authed.get(CALENDAR_PATH, params={"from": "not-a-date"})
    assert response.status_code == 422
