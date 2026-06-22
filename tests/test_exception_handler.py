"""Tests for the global unhandled-exception handler in main.py.

Two things are pinned here:

  (a) An UNEXPECTED, otherwise-uncaught exception at the app boundary becomes a clean,
      governed 500: status 500, the {"detail": ...} body shape the routes use, the fixed
      non-clinical message, and NO exception text / class name / traceback leaking into the
      body. The real exception is still logged server-side (asserted via caplog), so
      debugging is unaffected. TestClient is built with raise_server_exceptions=False so
      the handler's RESPONSE is returned (the default would re-raise the exception into the
      test, bypassing the handler) - this is what a real HTTP client sees.

  (b) NO REGRESSION on the typed 4xx paths: an existing governed 404 (the alerts list when
      the caller has no care recipient) still returns its exact governed `detail`. This
      proves the catch-all Exception handler does not intercept FastAPI's HTTPException
      (HTTPException has its own handler), so every existing 4xx response is untouched.
"""

from __future__ import annotations

import logging

from starlette.testclient import TestClient

import app.routes.alerts as alerts_routes
import main
from app.auth import get_current_user
from app.config import settings
from app.services import profile as profile_service

# A unique route path used only by the unhandled-exception test. It is added to main.app for
# the duration of the test and removed afterward so the session-scoped `client` fixture other
# tests share is never left with a stray route.
_BOOM_PATH = "/__test_only_boom__"

# A sentinel string baked into the raised exception. The body must NOT contain it: that is
# how we prove no exception text leaks to the client.
_SECRET_INTERNAL = "supabase APIError PGRST-internal-leak-token"


def test_unhandled_exception_returns_governed_500_with_no_internals(caplog):
    async def _boom() -> None:
        raise RuntimeError(_SECRET_INTERNAL)

    main.app.add_api_route(_BOOM_PATH, _boom, methods=["GET"])
    try:
        # raise_server_exceptions=False: return the handler's response (what a real client
        # gets) instead of re-raising the exception into the test.
        with caplog.at_level(logging.ERROR):
            with TestClient(main.app, raise_server_exceptions=False) as test_client:
                response = test_client.get(_BOOM_PATH)
    finally:
        main.app.router.routes = [
            route
            for route in main.app.router.routes
            if getattr(route, "path", None) != _BOOM_PATH
        ]

    assert response.status_code == 500

    body = response.json()
    # Same body shape as the routes: {"detail": ...}, the fixed governed message, nothing else.
    assert body == {"detail": main.GENERIC_ERROR_DETAIL}

    # The governed message is calm and non-clinical, with no em or en dashes.
    assert main.GENERIC_ERROR_DETAIL == "Something went wrong on our end. Please try again."
    assert "—" not in main.GENERIC_ERROR_DETAIL  # em dash
    assert "–" not in main.GENERIC_ERROR_DETAIL  # en dash

    # No exception text, class name, or traceback leaks into the response body.
    raw = response.text
    assert _SECRET_INTERNAL not in raw
    assert "RuntimeError" not in raw
    assert "Traceback" not in raw

    # The real exception IS logged server-side (so debugging still works), and the
    # log carries the traceback (logger.exception), not just the message.
    assert any(record.exc_info for record in caplog.records)
    assert any(_SECRET_INTERNAL in record.getMessage() or
               (record.exc_info and _SECRET_INTERNAL in str(record.exc_info[1]))
               for record in caplog.records)


def test_unhandled_exception_500_carries_cors_header_for_an_allowed_origin():
    """A genuine 500 must stay READABLE cross-origin. The catch-all sits OUTSIDE CORSMiddleware, so it
    echoes an allowed Origin itself; otherwise the browser reports a real 500 (e.g. a transient Supabase
    outage) as a CORS block instead of the governed 'try again'. A disallowed origin is never echoed."""

    async def _boom() -> None:
        raise RuntimeError("boom")

    allowed = settings.cors_allow_origins[0]
    main.app.add_api_route(_BOOM_PATH, _boom, methods=["GET"])
    try:
        with TestClient(main.app, raise_server_exceptions=False) as test_client:
            allowed_resp = test_client.get(_BOOM_PATH, headers={"origin": allowed})
            denied_resp = test_client.get(_BOOM_PATH, headers={"origin": "https://evil.example"})
    finally:
        main.app.router.routes = [
            route
            for route in main.app.router.routes
            if getattr(route, "path", None) != _BOOM_PATH
        ]

    # The 500 stays readable for an allowed origin (the header echoes that origin, with credentials).
    assert allowed_resp.status_code == 500
    assert allowed_resp.headers.get("access-control-allow-origin") == allowed
    assert allowed_resp.headers.get("access-control-allow-credentials") == "true"

    # A disallowed origin is NEVER echoed (no wildcard-with-credentials leak).
    assert denied_resp.status_code == 500
    assert "access-control-allow-origin" not in denied_resp.headers


def test_existing_governed_404_is_unaffected(client, monkeypatch):
    """A typed 4xx path keeps its exact governed copy: the catch-all does not swallow it."""

    def _raise(user, child_id=None):
        raise profile_service.ChildNotFoundError("no recipient")

    monkeypatch.setattr(alerts_routes.alerts_service, "list_active_alerts", _raise)
    client.app.dependency_overrides[get_current_user] = lambda: object()
    try:
        response = client.get("/api/v1/alerts")
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 404
    # The route's own governed detail, unchanged by the global handler.
    assert response.json() == {"detail": "No care recipient found"}
