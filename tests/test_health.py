"""Smoke tests that need no Supabase connection.

Covers the root health route (must not touch Supabase) and the CORS-origins
parsing introduced by the Task 0 security hardening.
"""

from app.config import Settings

# Keys the root route in main.py returns. Pinned here so a change to the
# contract is a deliberate, reviewed edit.
EXPECTED_ROOT_KEYS = {
    "message",
    "status",
    "version",
    "docs_url",
    "redoc_url",
    "openapi_url",
}


def test_root_returns_200_and_expected_keys(client):
    response = client.get("/")
    assert response.status_code == 200

    body = response.json()
    assert EXPECTED_ROOT_KEYS.issubset(body.keys())
    assert body["status"] == "healthy"


def test_cors_allow_origins_parses_comma_separated_value():
    # Constructed directly (not from ambient env or .env) so the parsing logic
    # is exercised in isolation: a comma-separated string becomes a trimmed list.
    settings = Settings(
        CORS_ALLOW_ORIGINS="https://app.example.com, https://www.example.com ,https://example.com"
    )
    parsed = settings.cors_allow_origins

    assert isinstance(parsed, list)
    assert parsed == [
        "https://app.example.com",
        "https://www.example.com",
        "https://example.com",
    ]


def test_cors_allow_origins_ignores_empty_entries():
    settings = Settings(CORS_ALLOW_ORIGINS="https://example.com,,  ,")
    assert settings.cors_allow_origins == ["https://example.com"]
