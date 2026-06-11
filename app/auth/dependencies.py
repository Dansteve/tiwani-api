"""The current-user FastAPI dependency.

Required on EVERY data route (HardRules/Api/Modules/Auth.md). It resolves the
bearer token from the Authorization header to a Supabase user and is the first
line of user scoping; Row Level Security on every table is the database backstop.

Mechanism: read 'Authorization: Bearer <token>', hand the token to Supabase Auth
(client.auth.get_user(token), which validates the JWT and returns the user), and
return an AuthedUser carrying the user id (the scope key for every read and
write) plus the validated access token (which a route passes to
get_anon_client(token) so its queries run under that user's RLS). The api issues
no JWT of its own; Supabase issues and validates tokens.

Error contract (HardRules/Api/SETUP.md): a missing or invalid token is 401. A
cross-user access attempt is 404 and is enforced downstream by RLS plus
user-scoped queries, not here (this dependency only authenticates).

Usage on a data route:

    from fastapi import Depends
    from app.auth import AuthedUser, get_current_user

    @router.get("/children")
    def list_children(user: AuthedUser = Depends(get_current_user)):
        client = get_anon_client(user.access_token)  # RLS-scoped to this user
        ...

This module is import-safe and makes no network call at import time; the call to
Supabase happens only inside the dependency, per request.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_anon_client

# auto_error=False so a missing header yields our own 401 envelope rather than
# FastAPI's default 403; we raise the 401 explicitly below.
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthedUser:
    """The authenticated user resolved from the Supabase session.

    id is the scope key for every user-scoped query. access_token is the
    validated bearer token, passed to get_anon_client(token) so a route's
    queries execute under this user's Row Level Security.
    """

    id: str
    email: Optional[str]
    access_token: str


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthedUser:
    """Resolve the bearer token to the current user, or raise 401.

    Raises 401 when the Authorization header is missing, malformed, or carries a
    token Supabase cannot validate (expired, tampered, or for another project).
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Supabase validates the JWT and returns the user. A bad token raises or
    # returns no user; either way the request is unauthenticated. We do not leak
    # the underlying auth error to the caller.
    try:
        response = get_anon_client().auth.get_user(token)
    except Exception as exc:  # noqa: BLE001  (any auth failure is a 401, not a 500)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthedUser(id=user.id, email=getattr(user, "email", None), access_token=token)
