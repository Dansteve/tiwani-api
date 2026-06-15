"""Tests for the v1 check-in moment endpoint (the carer "A moment for you" read).

The check-in moment (ProductReview.md item 9, the psychiatrist board's SAFE shape) is an
OPTIONAL, signpost-only, EPHEMERAL read: it acknowledges the carer and points to
community/statutory + crisis-capable support, it NEVER scores the carer, and it stores
NOTHING. These tests run with no live Supabase (the route has no DB layer; there is nothing
to persist), against main.app via TestClient.

What they pin:
  - AUTH: 401 without a bearer token.
  - THE SIGN-OFF GATE: 404 while the OFF-by-default flag is disabled (the surface does not
    exist for users until psychiatrist + DPO sign-off enables CHECKIN_MOMENT_ENABLED).
  - THE RESPONSE SHAPE + VERBATIM GOVERNED COPY when the flag is enabled: the
    {tap, intro, acknowledgement, signposts, needs_signoff} shape, the strings matching the
    engine's governed copy exactly (the app renders the api's text, authors none), the
    optional coarse tap branching the signposting, and the hard branch carrying the
    crisis-capable carer route.
  - EPHEMERAL: an unknown tap is a 422 (no free-text ingress); the surface has no service /
    DB module to write through.
"""

from __future__ import annotations

import pytest

from app.auth import AuthedUser, get_current_user
from app.engines.checkin import MomentTap, render_moment
from app.engines.checkin.flag import CHECKIN_MOMENT_FLAG_ENV

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

MOMENT_PATH = "/api/v1/checkin/moment"


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def enabled(monkeypatch):
    """Enable the OFF-by-default surface for the duration of a test (sign-off simulation)."""
    monkeypatch.setenv(CHECKIN_MOMENT_FLAG_ENV, "true")
    yield


# ---------------------------------------------------------------------------
# auth required (401)
# ---------------------------------------------------------------------------


def test_moment_requires_authentication(client, enabled):
    # Even with the surface enabled, no bearer token is a 401 (the current-user dependency).
    response = client.get(MOMENT_PATH)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# the sign-off gate (404 while OFF by default)
# ---------------------------------------------------------------------------


def test_moment_is_404_when_the_flag_is_off(authed, monkeypatch):
    # The flag is OFF by default: the surface does not exist for users. Authenticated, but
    # still a 404 (not a 403), so a probe cannot tell the route is there.
    monkeypatch.delenv(CHECKIN_MOMENT_FLAG_ENV, raising=False)
    response = authed.get(MOMENT_PATH)
    assert response.status_code == 404


@pytest.mark.parametrize("value", ["0", "false", "off", "", "no"])
def test_moment_stays_404_for_non_truthy_flag_values(authed, monkeypatch, value):
    monkeypatch.setenv(CHECKIN_MOMENT_FLAG_ENV, value)
    response = authed.get(MOMENT_PATH)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# the response shape + verbatim governed copy (flag enabled)
# ---------------------------------------------------------------------------


def test_moment_default_branch_returns_the_governed_shape(authed, enabled):
    response = authed.get(MOMENT_PATH)
    assert response.status_code == 200
    body = response.json()

    expected = render_moment(MomentTap.NONE)
    # The shape the app mirrors.
    assert set(body) == {"tap", "intro", "acknowledgement", "signposts", "needs_signoff"}
    assert body["tap"] == "none"
    # The copy is the engine's GOVERNED text, verbatim (the app authors none).
    assert body["intro"] == expected.intro
    assert body["acknowledgement"] == expected.acknowledgement
    assert body["signposts"] == [
        {"label": s.label, "url": s.url} for s in expected.signposts
    ]
    # A standing reminder this surface is sign-off gated.
    assert body["needs_signoff"] is True


@pytest.mark.parametrize("tap", ["none", "okay", "a_lot", "hard"])
def test_moment_each_tap_branch_renders_its_governed_copy(authed, enabled, tap):
    response = authed.get(MOMENT_PATH, params={"tap": tap})
    assert response.status_code == 200
    body = response.json()

    expected = render_moment(MomentTap(tap))
    assert body["tap"] == tap
    assert body["intro"] == expected.intro
    assert body["acknowledgement"] == expected.acknowledgement
    assert body["signposts"] == [
        {"label": s.label, "url": s.url} for s in expected.signposts
    ]


def test_moment_hard_branch_signposts_the_crisis_capable_carer_route(authed, enabled):
    # Condition 5: a hard-day answer signposts real support and a crisis-capable carer route
    # (talk to someone TODAY). The Samaritans + NHS 111 routes must be present.
    response = authed.get(MOMENT_PATH, params={"tap": "hard"})
    assert response.status_code == 200
    labels = [s["label"] for s in response.json()["signposts"]]
    assert any("116 123" in label for label in labels), labels
    assert any("111" in label for label in labels), labels


def test_moment_rejects_an_unknown_tap_value(authed, enabled):
    # The only input is the COARSE enum tap; a value outside it is a 422 (no free-text path,
    # no fine mood scale). This is the structured-only ingress (condition 2).
    response = authed.get(MOMENT_PATH, params={"tap": "terrible"})
    assert response.status_code == 422


def test_moment_has_no_persistence_layer():
    # EPHEMERAL (condition 3): the surface stores nothing, so there is deliberately NO
    # checkin service / DB module. Importing one must fail (it does not exist).
    with pytest.raises(ModuleNotFoundError):
        __import__("app.services.checkin")
