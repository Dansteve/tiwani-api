"""Supabase clients for the v3 rebuild.

Two clients, per HardRules/Api/SETUP.md and HardRules/Api/Modules/Auth.md:

  - a PER-REQUEST anon-scoped client that carries the caller's bearer token, so
    Row Level Security applies and the database returns only that user's rows;
  - a single SERVICE-ROLE client for the narrow admin operations that must
    bypass RLS deliberately (for example creating the user_profile row at
    sign-up). It is never the default for a data read or write.

Configuration is env-only (app/config.py); there are no secrets in source. The
supabase client object is cheap to construct and only opens a network
connection on an actual call, so building one per request is fine and nothing
here touches a live database at import time.

This module is additive: the prototype's app/database.py (Supabase clients plus
the unused SQLAlchemy engine) is left in place for the multi-developer
prototype routes and is replaced when those routes are rebuilt to v3. New v3
code uses this module.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from supabase import Client, create_client


def get_anon_client(access_token: str | None = None) -> Client:
    """Return an anon-key Supabase client, optionally carrying a user's session.

    The anon key plus the caller's bearer token is the RLS-scoped path: with a
    valid token set, every query the client runs is filtered by Row Level
    Security to the authenticated user's rows. Call this PER REQUEST with the
    token from the Authorization header (see app/auth). With no token it is an
    unauthenticated anon client (used only to resolve a token to a user).

    A fresh client is returned each call rather than mutating a shared one, so
    one request's session never leaks into another's.
    """
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if access_token:
        # PostgREST sends this Authorization header on every query, so RLS sees
        # the user. The empty refresh token is intentional: the api validates a
        # token per request and does not manage session refresh on the user's
        # behalf (Supabase Auth owns the session lifecycle).
        client.postgrest.auth(access_token)
    return client


@lru_cache(maxsize=1)
def get_service_client() -> Client:
    """Return the shared service-role Supabase client (RLS bypassed).

    Used ONLY for the narrow admin operations that must bypass RLS on purpose,
    for example creating a user_profile row at sign-up. It is never the default
    client for a user-facing read or write. Cached because it holds no
    per-request state; the service-role key comes from the environment.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
