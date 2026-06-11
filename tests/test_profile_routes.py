"""No-DB route tests for the v3 profile/child/onboarding endpoints.

These drive the real FastAPI app (main.app) through a TestClient. Two seams keep
them off a live Supabase (blocked in the sandbox; the task requires mocking):
  - the current-user dependency is overridden with a fixed AuthedUser for the
    authenticated cases (and left real for the 401 cases, which short-circuit on a
    missing token before any network call);
  - the profile data service functions are monkeypatched, so no Supabase call is
    made and the route's parse -> call-service -> serialize wiring is what is
    tested, plus the 401 / 400 / 404 / 422 error contract.

They pin: auth is required (401 with no token), the success shapes (200 / 201),
not-found (404), empty-update (400), and the structured-code validation (422 for
a bad support level, a bad tag, or a single-select violation).
"""

from datetime import datetime, timezone

import pytest

import app.routes.profile_v3 as routes
from app.auth import AuthedUser, get_current_user

NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

PROFILE_ROW = {
    "id": "u-1",
    "email": "ada@example.com",
    "first_name": "Ada",
    "subscription_tier": "free",
    "onboarding_complete": False,
    "created_at": NOW,
    "updated_at": NOW,
}

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


@pytest.fixture
def authed(client):
    """Override the current-user dependency with a fixed authed user."""
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required (401): real dependency, no token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v3/profile"),
        ("put", "/api/v3/profile"),
        ("post", "/api/v3/child"),
        ("get", "/api/v3/child"),
        ("put", "/api/v3/child/c-1"),
        ("post", "/api/v3/onboarding"),
    ],
)
def test_routes_require_authentication(client, method, path):
    # No Authorization header => the current-user dependency raises 401 before any
    # Supabase call (it short-circuits on missing credentials). GET takes no body
    # in this TestClient; only the write methods carry a json payload.
    if method == "get":
        response = client.get(path)
    else:
        response = getattr(client, method)(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /profile (get-or-create)
# ---------------------------------------------------------------------------


def test_get_profile_returns_profile(authed, monkeypatch):
    monkeypatch.setattr(routes.profile_service, "get_or_create_profile", lambda user: PROFILE_ROW)
    response = authed.get("/api/v3/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "u-1"
    assert body["first_name"] == "Ada"
    assert body["onboarding_complete"] is False


# ---------------------------------------------------------------------------
# PUT /profile
# ---------------------------------------------------------------------------


def test_update_profile_success(authed, monkeypatch):
    updated = {**PROFILE_ROW, "onboarding_complete": True}
    monkeypatch.setattr(
        routes.profile_service, "update_profile", lambda user, fields: updated
    )
    response = authed.put("/api/v3/profile", json={"onboarding_complete": True})
    assert response.status_code == 200
    assert response.json()["onboarding_complete"] is True


def test_update_profile_empty_body_is_400(authed):
    response = authed.put("/api/v3/profile", json={})
    assert response.status_code == 400


def test_update_profile_not_found_is_404(authed, monkeypatch):
    monkeypatch.setattr(routes.profile_service, "update_profile", lambda user, fields: None)
    response = authed.put("/api/v3/profile", json={"first_name": "Ada"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /child
# ---------------------------------------------------------------------------


def test_create_child_success_returns_201(authed, monkeypatch):
    monkeypatch.setattr(routes.profile_service, "create_child", lambda user, fields: CHILD_ROW)
    response = authed.post(
        "/api/v3/child",
        json={
            "name": "Sam",
            "age_band": "6-8",
            "support_level_code": "SL-MED",
            "tags": ["SN-NOISE", "CM-MIXED"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == "u-1"
    assert body["support_level_code"] == "SL-MED"


def test_create_child_rejects_unknown_support_level_422(authed):
    response = authed.post(
        "/api/v3/child", json={"name": "Sam", "support_level_code": "SL-EXTREME"}
    )
    assert response.status_code == 422


def test_create_child_rejects_unknown_tag_422(authed):
    response = authed.post("/api/v3/child", json={"name": "Sam", "tags": ["XX-BOGUS"]})
    assert response.status_code == 422


def test_create_child_requires_name_422(authed):
    response = authed.post("/api/v3/child", json={"age_band": "6-8"})
    assert response.status_code == 422


def test_create_child_rejects_single_select_violation_422(authed):
    # Two Recovery tags violates the single-select rule on the create path too.
    response = authed.post(
        "/api/v3/child", json={"name": "Sam", "tags": ["RC-SHORT", "RC-MOD"]}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /child
# ---------------------------------------------------------------------------


def test_get_child_success(authed, monkeypatch):
    monkeypatch.setattr(routes.profile_service, "get_child", lambda user: CHILD_ROW)
    response = authed.get("/api/v3/child")
    assert response.status_code == 200
    assert response.json()["name"] == "Sam"


def test_get_child_not_found_is_404(authed, monkeypatch):
    monkeypatch.setattr(routes.profile_service, "get_child", lambda user: None)
    response = authed.get("/api/v3/child")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /child/{id}
# ---------------------------------------------------------------------------


def test_update_child_success(authed, monkeypatch):
    updated = {**CHILD_ROW, "name": "Samuel"}
    monkeypatch.setattr(
        routes.profile_service, "update_child", lambda user, child_id, fields: updated
    )
    response = authed.put("/api/v3/child/c-1", json={"name": "Samuel"})
    assert response.status_code == 200
    assert response.json()["name"] == "Samuel"


def test_update_child_empty_body_is_400(authed):
    response = authed.put("/api/v3/child/c-1", json={})
    assert response.status_code == 400


def test_update_child_not_found_is_404(authed, monkeypatch):
    monkeypatch.setattr(
        routes.profile_service, "update_child", lambda user, child_id, fields: None
    )
    response = authed.put("/api/v3/child/c-forged", json={"name": "X"})
    assert response.status_code == 404


def test_update_child_rejects_single_select_violation_422(authed):
    # Two Communication tags violates the single-select rule (SeedData.md).
    response = authed.put("/api/v3/child/c-1", json={"tags": ["CM-MIXED", "CM-VERBAL"]})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /onboarding
# ---------------------------------------------------------------------------


def test_onboarding_success_returns_profile_and_child(authed, monkeypatch):
    completed_profile = {**PROFILE_ROW, "onboarding_complete": True}
    monkeypatch.setattr(
        routes.profile_service,
        "complete_onboarding",
        lambda user, payload: {"profile": completed_profile, "child": CHILD_ROW},
    )
    response = authed.post(
        "/api/v3/onboarding",
        json={
            "name": "Sam",
            "age_band": "6-8",
            "support_level_code": "SL-MED",
            "tags": ["SN-NOISE", "TR-CHANGE", "CM-MIXED", "RC-VAR"],
            "first_activity": {"chapter": "mornings", "activity_type": "school-run"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_complete"] is True
    assert body["child"]["name"] == "Sam"


def test_onboarding_requires_support_level_422(authed):
    # support_level_code is required on the onboarding payload (sets the multiplier).
    response = authed.post("/api/v3/onboarding", json={"name": "Sam", "tags": []})
    assert response.status_code == 422


def test_onboarding_rejects_two_recovery_tags_422(authed):
    response = authed.post(
        "/api/v3/onboarding",
        json={
            "name": "Sam",
            "support_level_code": "SL-LOW",
            "tags": ["RC-SHORT", "RC-EXT"],
        },
    )
    assert response.status_code == 422


def test_onboarding_rejects_unknown_tag_422(authed):
    response = authed.post(
        "/api/v3/onboarding",
        json={"name": "Sam", "support_level_code": "SL-LOW", "tags": ["ZZ-NOPE"]},
    )
    assert response.status_code == 422
