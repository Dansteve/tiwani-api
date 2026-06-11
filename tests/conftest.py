"""Shared pytest fixtures for the tiwani-api test suite.

These tests run without any real Supabase connection. Placeholder env vars are
set before the app is imported so that:
  - app.config.Settings loads without real secrets, and
  - app.database (imported transitively by the routers) does not raise on an
    empty DATABASE_URL and constructs its Supabase clients against dummy URLs
    (the supabase client only opens a connection on an actual call, which these
    tests never make: they exercise the root route and config parsing only).
"""

import os

import pytest

# Force safe dummy values before importing the app, overriding any real values
# a developer may have exported, so the suite can never reach real Supabase.
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_KEY"] = "dummy-anon-key"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy-service-role-key"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/dummy"

from starlette.testclient import TestClient  # noqa: E402  (import after env setup)

import main  # noqa: E402  (import after env setup)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """A FastAPI TestClient for the app defined in main.py."""
    with TestClient(main.app) as test_client:
        yield test_client
