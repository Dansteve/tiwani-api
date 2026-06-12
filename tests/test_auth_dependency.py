"""No-DB tests for the current-user dependency (app/auth/dependencies).

The dependency's only network call is auth.get_user(token), which is monkeypatched
here so the suite never reaches a live Supabase (the conftest also forces dummy
Supabase env). These pin the error contract: missing / empty / invalid tokens are
401, and a resolved user is returned with its id and the access token attached.

The 401 authentication contract lives in get_current_user_allow_deleted (the pure
authenticator); get_current_user wraps it and ADDS the soft-delete closure block
(410 for a closed account). These tests target the pure authenticator for the 401
contract; the closure block is covered in test_account_routes.py.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.auth.dependencies as deps
from app.auth import AuthedUser, get_current_user_allow_deleted


class _FakeUser:
    def __init__(self, user_id, email):
        self.id = user_id
        self.email = email


class _FakeUserResponse:
    def __init__(self, user):
        self.user = user


class _FakeAuth:
    def __init__(self, behaviour):
        self._behaviour = behaviour

    def get_user(self, token):
        return self._behaviour(token)


class _FakeClient:
    def __init__(self, behaviour):
        self.auth = _FakeAuth(behaviour)


def _patch_anon_client(monkeypatch, behaviour):
    """Make get_anon_client() (no token) return a fake whose auth.get_user runs behaviour."""
    monkeypatch.setattr(deps, "get_anon_client", lambda *args, **kwargs: _FakeClient(behaviour))


def test_missing_credentials_raises_401(monkeypatch):
    # No Authorization header => credentials is None => 401, never a network call.
    called = {"hit": False}

    def behaviour(token):
        called["hit"] = True
        return None

    _patch_anon_client(monkeypatch, behaviour)
    with pytest.raises(HTTPException) as exc:
        get_current_user_allow_deleted(credentials=None)
    assert exc.value.status_code == 401
    assert called["hit"] is False  # short-circuits before touching Supabase


def test_empty_token_raises_401(monkeypatch):
    _patch_anon_client(monkeypatch, lambda token: None)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
    with pytest.raises(HTTPException) as exc:
        get_current_user_allow_deleted(credentials=creds)
    assert exc.value.status_code == 401


def test_invalid_token_get_user_raises_maps_to_401(monkeypatch):
    # Supabase rejecting the token (raising) must surface as 401, not 500.
    def behaviour(token):
        raise ValueError("invalid JWT")

    _patch_anon_client(monkeypatch, behaviour)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token.here")
    with pytest.raises(HTTPException) as exc:
        get_current_user_allow_deleted(credentials=creds)
    assert exc.value.status_code == 401


def test_token_resolving_to_no_user_raises_401(monkeypatch):
    # get_user returns a response with user=None => unauthenticated => 401.
    _patch_anon_client(monkeypatch, lambda token: _FakeUserResponse(user=None))
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="some.token")
    with pytest.raises(HTTPException) as exc:
        get_current_user_allow_deleted(credentials=creds)
    assert exc.value.status_code == 401


def test_valid_token_returns_authed_user(monkeypatch):
    user = _FakeUser(user_id="user-123", email="coordinator@example.com")
    _patch_anon_client(monkeypatch, lambda token: _FakeUserResponse(user=user))
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="good.jwt.token")

    result = get_current_user_allow_deleted(credentials=creds)

    assert isinstance(result, AuthedUser)
    assert result.id == "user-123"
    assert result.email == "coordinator@example.com"
    # The validated token is attached so a route can build an RLS-scoped client.
    assert result.access_token == "good.jwt.token"


# ---------------------------------------------------------------------------
# get_current_user: the soft-delete closure block (410) on top of the auth above
# ---------------------------------------------------------------------------


def test_get_current_user_passes_through_an_active_account(monkeypatch):
    # An active account (deleted_at not set) is returned unchanged: get_current_user
    # authenticates via the allow-deleted path, then the closure check says "not deleted".
    import app.services.account as account_service

    authed = AuthedUser(id="u-1", email="ada@example.com", access_token="tok")
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: False)

    result = deps.get_current_user(user=authed)

    assert result is authed


def test_get_current_user_blocks_a_closed_account_with_410(monkeypatch):
    # A soft-deleted account (deleted_at set) is rejected with 410 Gone, so it can
    # neither read nor write any route that depends on get_current_user.
    import app.services.account as account_service

    authed = AuthedUser(id="u-1", email="ada@example.com", access_token="tok")
    monkeypatch.setattr(account_service, "is_account_deleted", lambda user: True)

    with pytest.raises(HTTPException) as exc:
        deps.get_current_user(user=authed)
    assert exc.value.status_code == 410
