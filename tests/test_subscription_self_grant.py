"""The self-grant fix, proven (Docs/FeatureDecisions.md, Subscription precondition 2).

A user must NOT be able to promote their own subscription tier. The hole was:
`PUT /api/v3/profile {"subscription_tier": "premium"}` reached an update that the
user_profile RLS UPDATE policy permitted on any column, so a free user could self-promote.
The fix removes subscription_tier from the writable surface (UserProfileUpdate has no such
field; UserProfileBase no longer carries it), so the value is dropped before the update is
built, AND the tier column has no user write policy (migration 0018: subscription state is
owner-SELECT-only). This file proves the API half: the route NEVER passes subscription_tier
to update_profile, even when a client sends it.

The DB half (RLS forbids a user writing the tier at all) is proven by the real-Postgres RLS
test (tests/test_subscription_rls_real_postgres.py), which asserts an authenticated user
cannot UPDATE its own subscription row.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.routes.profile_v3 as routes
from app.auth import get_current_user
from app.models.user_profile import UserProfileUpdate

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
AUTHED_ID = "u-1"


class _AuthedUser:
    id = AUTHED_ID
    email = "ada@example.com"
    access_token = "tok-abc"


PROFILE_ROW = {
    "id": AUTHED_ID,
    "email": "ada@example.com",
    "first_name": "Ada",
    "subscription_tier": "free",
    "onboarding_complete": False,
    "created_at": NOW,
    "updated_at": NOW,
}


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: _AuthedUser()
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


def test_update_model_drops_a_client_supplied_tier():
    # The model is the first line: subscription_tier is not a field, so even when a client
    # supplies it, the set-only dump used by the route never contains it.
    fields = UserProfileUpdate(
        first_name="Ada", subscription_tier="premium"
    ).model_dump(exclude_unset=True)
    assert "subscription_tier" not in fields
    assert fields == {"first_name": "Ada"}


def test_put_profile_cannot_self_promote_tier(authed, monkeypatch):
    # Drive the real PUT /api/v3/profile route with a self-promotion attempt and capture the
    # exact fields handed to the service. The tier must be ABSENT: the service is never asked
    # to write subscription_tier, so a user cannot promote themselves through the api.
    captured = {}

    def fake_update_profile(user, fields):
        captured["fields"] = fields
        # The row the DB would return is unchanged (still free): the tier was never written.
        return {**PROFILE_ROW, "first_name": fields.get("first_name", "Ada")}

    monkeypatch.setattr(routes.profile_service, "update_profile", fake_update_profile)

    response = authed.put(
        "/api/v3/profile",
        json={"first_name": "Ada", "subscription_tier": "premium"},
    )

    assert response.status_code == 200
    # The crux: the field handed to the data layer carries NO subscription_tier.
    assert "subscription_tier" not in captured["fields"]
    assert captured["fields"] == {"first_name": "Ada"}
    # And the response tier is unchanged (free), never the attempted premium.
    assert response.json()["subscription_tier"] == "free"


def test_put_profile_with_only_a_tier_is_a_no_op_400(authed, monkeypatch):
    # A request whose ONLY field is the (now-unknown) subscription_tier reduces to an empty
    # update once the field is dropped, so the route returns 400 (no fields provided): there
    # is no path by which a tier-only PUT writes anything.
    called = {"update": False}

    def fake_update_profile(user, fields):  # pragma: no cover - must not be reached
        called["update"] = True
        return PROFILE_ROW

    monkeypatch.setattr(routes.profile_service, "update_profile", fake_update_profile)

    response = authed.put("/api/v3/profile", json={"subscription_tier": "premium"})

    assert response.status_code == 400
    assert called["update"] is False
