"""No-DB route tests for the v3 account endpoints + the soft-delete access block.

These drive the real FastAPI app (main.app) through the shared TestClient. The seams keep
them off a live Supabase (same approach as test_profile_routes):
  - the authenticator dependency is overridden with a fixed AuthedUser for the authed cases
    (and left real for the 401 cases, which short-circuit on a missing token);
  - the account service functions are monkeypatched, so no Supabase call is made and only
    the route wiring + the access block are exercised.

They pin: auth is required (401), GET /me/export returns the caller's data as a downloadable
JSON attachment, POST /me/delete returns the soft-delete confirmation, and a CLOSED
(soft-deleted) account is blocked on a normal data route with 410 while it can still hit the
self-service routes (the allow-deleted authenticator).
"""

from datetime import datetime, timezone

import pytest

import app.routes.account_v3 as routes
import app.services.account as account_service
from app.auth import AuthedUser, get_current_user_allow_deleted

NOW_ISO = datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc).isoformat()

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")


@pytest.fixture
def authed(client):
    """Override the allow-deleted authenticator with a fixed user.

    The self-service routes depend on get_current_user_allow_deleted; overriding it also
    feeds get_current_user (which depends on it), so this one override authenticates both
    the account routes and the normal routes used in the access-block test.
    """
    client.app.dependency_overrides[get_current_user_allow_deleted] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user_allow_deleted, None)


# ---------------------------------------------------------------------------
# auth required (401): real dependency, no token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v3/me/export"),
        ("post", "/api/v3/me/delete"),
        ("get", "/api/v3/me/account-status"),
        ("post", "/api/v3/me/reactivate"),
    ],
)
def test_account_routes_require_authentication(client, method, path):
    if method == "get":
        response = client.get(path)
    else:
        response = client.post(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /me/export
# ---------------------------------------------------------------------------


def test_export_returns_downloadable_json_of_callers_data(authed, monkeypatch):
    document = {
        "user_profile": {"id": "u-1", "first_name": "Ada"},
        "child_profile": [{"id": "c-1", "user_id": "u-1", "name": "Sam"}],
        "activity_record": [],
        "pulse_record": [],
        "lci_snapshot": [],
        "alert_record": [],
        "card_record": [],
    }
    monkeypatch.setattr(routes.account_service, "export_account", lambda user: document)

    response = authed.get("/api/v3/me/export")

    assert response.status_code == 200
    # Downloaded as a file, not rendered inline.
    assert "attachment" in response.headers.get("content-disposition", "")
    assert ".json" in response.headers.get("content-disposition", "")
    body = response.json()
    assert body["user_profile"]["id"] == "u-1"
    assert body["child_profile"][0]["name"] == "Sam"
    assert body["pulse_record"] == []


# ---------------------------------------------------------------------------
# POST /me/delete
# ---------------------------------------------------------------------------


def test_delete_returns_soft_delete_confirmation(authed, monkeypatch):
    monkeypatch.setattr(
        routes.account_service,
        "soft_delete_account",
        lambda user: {"deleted": True, "deleted_at": NOW_ISO},
    )
    response = authed.post("/api/v3/me/delete")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["deleted_at"].startswith("2026-06-12T10:00:00")


def test_delete_is_idempotent_a_second_call_still_confirms(authed, monkeypatch):
    # The route depends on the allow-deleted authenticator, so an already-closed account is
    # not pre-empted by the 410 block: a repeat delete still returns a 200 confirmation.
    monkeypatch.setattr(
        routes.account_service,
        "soft_delete_account",
        lambda user: {"deleted": True, "deleted_at": NOW_ISO},
    )
    first = authed.post("/api/v3/me/delete")
    second = authed.post("/api/v3/me/delete")
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deleted"] is True


# ---------------------------------------------------------------------------
# the soft-delete access block (410 on a normal route)
# ---------------------------------------------------------------------------


def test_closed_account_is_blocked_on_a_normal_route_with_410(authed, monkeypatch):
    # A closed account (is_account_deleted True) hitting a NORMAL data route (GET /profile,
    # which depends on get_current_user) is rejected with 410 Gone before the route runs.
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: True)
    response = authed.get("/api/v3/profile")
    assert response.status_code == 410


def test_active_account_passes_the_block_on_a_normal_route(authed, monkeypatch):
    # The same route for an ACTIVE account (is_account_deleted False) is NOT blocked; it
    # reaches the route (the profile service is stubbed so no Supabase call is made).
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: False)
    import app.routes.profile_v3 as profile_routes

    profile_row = {
        "id": "u-1",
        "email": "ada@example.com",
        "first_name": "Ada",
        "subscription_tier": "free",
        "onboarding_complete": False,
        "created_at": NOW_ISO,
        "updated_at": NOW_ISO,
    }
    monkeypatch.setattr(
        profile_routes.profile_service, "get_or_create_profile", lambda user: profile_row
    )
    response = authed.get("/api/v3/profile")
    assert response.status_code == 200


def test_closed_account_can_still_reach_the_self_service_routes(authed, monkeypatch):
    # A closed account is blocked on normal routes but must still reach /me/export and
    # /me/delete (the allow-deleted authenticator), so it can export and re-close.
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: True)
    monkeypatch.setattr(
        routes.account_service,
        "soft_delete_account",
        lambda user: {"deleted": True, "deleted_at": NOW_ISO},
    )
    response = authed.post("/api/v3/me/delete")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


# ---------------------------------------------------------------------------
# GET /me/account-status (the post-login closure check; allow-deleted dependency)
# ---------------------------------------------------------------------------


def test_account_status_returns_the_recovery_window_shape(authed, monkeypatch):
    due = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc).isoformat()
    monkeypatch.setattr(
        routes.account_service,
        "account_status",
        lambda user: {
            "deleted": True,
            "deleted_at": NOW_ISO,
            "hard_delete_due_at": due,
            "reactivatable": True,
        },
    )
    response = authed.get("/api/v3/me/account-status")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["reactivatable"] is True
    assert body["deleted_at"].startswith("2026-06-12T10:00:00")
    assert body["hard_delete_due_at"].startswith("2026-09-10T10:00:00")


def test_account_status_works_for_a_soft_deleted_caller(authed, monkeypatch):
    # The whole point: a SOFT-DELETED account must reach account-status (the allow-deleted
    # dependency), so the 410 block does NOT pre-empt it.
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: True)
    monkeypatch.setattr(
        routes.account_service,
        "account_status",
        lambda user: {
            "deleted": True,
            "deleted_at": NOW_ISO,
            "hard_delete_due_at": NOW_ISO,
            "reactivatable": True,
        },
    )
    response = authed.get("/api/v3/me/account-status")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_account_status_active_account(authed, monkeypatch):
    monkeypatch.setattr(
        routes.account_service,
        "account_status",
        lambda user: {
            "deleted": False,
            "deleted_at": None,
            "hard_delete_due_at": None,
            "reactivatable": False,
        },
    )
    response = authed.get("/api/v3/me/account-status")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is False
    assert body["deleted_at"] is None
    assert body["hard_delete_due_at"] is None


# ---------------------------------------------------------------------------
# POST /me/reactivate (allow-deleted dependency; 90-day-window guard -> 410)
# ---------------------------------------------------------------------------


def test_reactivate_within_window_returns_reactivated(authed, monkeypatch):
    monkeypatch.setattr(
        routes.account_service, "reactivate_account", lambda user: {"reactivated": True}
    )
    response = authed.post("/api/v3/me/reactivate")
    assert response.status_code == 200
    assert response.json()["reactivated"] is True


def test_reactivate_works_for_a_soft_deleted_caller(authed, monkeypatch):
    # A SOFT-DELETED account must reach reactivate (the allow-deleted dependency): the 410
    # closure block must NOT pre-empt the reactivation route.
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: True)
    monkeypatch.setattr(
        routes.account_service, "reactivate_account", lambda user: {"reactivated": True}
    )
    response = authed.post("/api/v3/me/reactivate")
    assert response.status_code == 200
    assert response.json()["reactivated"] is True


def test_reactivate_past_window_is_410(authed, monkeypatch):
    # The service raises AccountPurgedError past the 90-day window; the route maps it to 410.
    def _raise(user):
        raise account_service.AccountPurgedError("past window")

    monkeypatch.setattr(routes.account_service, "reactivate_account", _raise)
    response = authed.post("/api/v3/me/reactivate")
    assert response.status_code == 410
