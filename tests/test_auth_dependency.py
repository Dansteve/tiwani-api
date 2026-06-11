"""No-DB tests for the current-user dependency (app/auth/dependencies).

The dependency's only network call is auth.get_user(token), which is monkeypatched
here so the suite never reaches a live Supabase (the conftest also forces dummy
Supabase env). These pin the error contract: missing / empty / invalid tokens are
401, and a resolved user is returned with its id and the access token attached.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.auth.dependencies as deps
from app.auth import AuthedUser, get_current_user


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
        get_current_user(credentials=None)
    assert exc.value.status_code == 401
    assert called["hit"] is False  # short-circuits before touching Supabase


def test_empty_token_raises_401(monkeypatch):
    _patch_anon_client(monkeypatch, lambda token: None)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds)
    assert exc.value.status_code == 401


def test_invalid_token_get_user_raises_maps_to_401(monkeypatch):
    # Supabase rejecting the token (raising) must surface as 401, not 500.
    def behaviour(token):
        raise ValueError("invalid JWT")

    _patch_anon_client(monkeypatch, behaviour)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token.here")
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds)
    assert exc.value.status_code == 401


def test_token_resolving_to_no_user_raises_401(monkeypatch):
    # get_user returns a response with user=None => unauthenticated => 401.
    _patch_anon_client(monkeypatch, lambda token: _FakeUserResponse(user=None))
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="some.token")
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials=creds)
    assert exc.value.status_code == 401


def test_valid_token_returns_authed_user(monkeypatch):
    user = _FakeUser(user_id="user-123", email="coordinator@example.com")
    _patch_anon_client(monkeypatch, lambda token: _FakeUserResponse(user=user))
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="good.jwt.token")

    result = get_current_user(credentials=creds)

    assert isinstance(result, AuthedUser)
    assert result.id == "user-123"
    assert result.email == "coordinator@example.com"
    # The validated token is attached so a route can build an RLS-scoped client.
    assert result.access_token == "good.jwt.token"
