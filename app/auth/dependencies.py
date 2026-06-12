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

Account closure (soft-delete): a Coordinator can CLOSE their account, which sets
user_profile.deleted_at (the data is retained for a 90-day recovery window, not
hard-deleted; migration 0013). A closed account must be unable to read or write.
get_current_user is the chokepoint that enforces this: after the token resolves to
a user, it reads that user's own user_profile.deleted_at under RLS and, if it is
set, raises 410 Gone. Because every v1 data route depends on get_current_user, a
soft-deleted account is blocked everywhere at once (fail-safe: a new route gets the
block for free). The SELF-SERVICE account routes (GET /me/export, POST /me/delete,
GET /me/account-status, POST /me/reactivate) must still work for a user acting on
their own closed account, so they depend on get_current_user_allow_deleted instead,
which authenticates WITHOUT the block (so the export reads up to the moment of
closure, the delete stays idempotent, and a soft-deleted caller can check their
status and REACTIVATE within the 90-day window, which clears deleted_at and lifts
the block).

Usage on a normal data route (blocked if the account is closed):

    from fastapi import Depends
    from app.auth import AuthedUser, get_current_user

    @router.get("/children")
    def list_children(user: AuthedUser = Depends(get_current_user)):
        client = get_anon_client(user.access_token)  # RLS-scoped to this user
        ...

This module is import-safe and makes no network call at import time; the calls to
Supabase happen only inside the dependency, per request.
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


def get_current_user_allow_deleted(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthedUser:
    """Resolve the bearer token to the current user, or raise 401. NO soft-delete block.

    Pure authentication: it validates the token and returns the AuthedUser, but does
    NOT check whether the account is closed (soft-deleted). The two self-service
    account routes (GET /me/export, POST /me/delete) depend on this so a user can act
    on their OWN account: export reads up to the moment of closure, and delete is
    idempotent (a deleted account can re-issue the soft-delete without being blocked).
    Every OTHER data route depends on get_current_user, which adds the closure block.

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


def get_current_user(
    user: AuthedUser = Depends(get_current_user_allow_deleted),
) -> AuthedUser:
    """Resolve the current user AND reject a closed (soft-deleted) account with 410.

    The default dependency for every v1 data route. It authenticates via
    get_current_user_allow_deleted, then reads the caller's OWN user_profile.deleted_at
    under RLS (get_anon_client(user.access_token), so the read can only ever see the
    caller's row). If deleted_at is set, the account has been closed (migration 0013);
    the request is rejected with 410 Gone, so a soft-deleted account can neither read
    nor write. A user with no profile row yet (a fresh sign-up before the profile is
    created) is treated as active. The deleted-account service owns the column read so
    the policy lives in one place (app/services/account).
    """
    # Imported here (not at module load) to keep this module import-safe and avoid a
    # cycle: app.services.account imports nothing from app.auth at import time.
    from app.services import account as account_service

    if account_service.is_account_deleted(user):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This account has been closed",
        )
    return user
