"""Rate-limiting tests (app/rate_limit.py + the wiring in main.py).

The api had NO throttle, so the public Continuity Card read, the invite redeem, and the
mints were a brute-force / guessable-code / spam surface (OWASP API4:2023). These pin: the
key functions (X-Forwarded-For per-IP, per-token for authed), the governed 429 envelope, and
that the strict per-route limit fires (a 21st card read from one IP is 429) while a different
IP keeps its own budget and a normal user under the limit is never blocked.

The limiter is OFF for the rest of the suite (conftest `_disable_rate_limiting_by_default`),
so the other ~780 tests do not trip the new limits; the `limited` fixture here turns it ON
with a clean store per test. The card route's Supabase call is mocked so the test is fast.
"""
import json

import pytest
from starlette.requests import Request

from app.rate_limit import (
    client_ip,
    limiter,
    rate_limit_exceeded_handler,
    token_key,
)


def make_request(headers=None, client=("1.2.3.4", 9999)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "headers": raw}
    if client is not None:
        scope["client"] = client
    return Request(scope)


# --- the key functions (pure) ---------------------------------------------------------------------

def test_client_ip_prefers_the_leftmost_forwarded_for():
    # Behind the Render / Cloud Run proxy the real client is the leftmost X-Forwarded-For entry, NOT
    # the socket (which is the load balancer).
    req = make_request({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, client=("127.0.0.1", 1))
    assert client_ip(req) == "9.9.9.9"


def test_client_ip_falls_back_to_the_socket_without_forwarded_for():
    assert client_ip(make_request({}, client=("203.0.113.7", 1))) == "203.0.113.7"


def test_token_key_is_per_token_for_authed_requests():
    a = token_key(make_request({"authorization": "Bearer aaa"}))
    b = token_key(make_request({"authorization": "Bearer bbb"}))
    assert a.startswith("tok:") and b.startswith("tok:")
    assert a != b  # different tokens -> different buckets


def test_token_key_is_stable_for_the_same_token():
    same_a = token_key(make_request({"authorization": "Bearer same"}))
    same_b = token_key(make_request({"authorization": "Bearer same"}))
    assert same_a == same_b


def test_token_key_falls_back_to_ip_when_unauthenticated():
    assert token_key(make_request({}, client=("198.51.100.4", 1))) == "198.51.100.4"


# --- the governed 429 -----------------------------------------------------------------------------

def test_429_handler_returns_the_governed_envelope_with_retry_after():
    resp = rate_limit_exceeded_handler(make_request(), exc=None)
    assert resp.status_code == 429
    assert json.loads(bytes(resp.body)) == {
        "detail": "Too many attempts. Please wait a moment and try again."
    }
    assert resp.headers["Retry-After"] == "60"
    # It must NOT leak which limit tripped.
    assert "5/minute" not in resp.body.decode()


# --- the limit actually fires (integration) -------------------------------------------------------

@pytest.fixture
def limited():
    """Turn the limiter ON for one test with a clean store; restore OFF afterward."""
    limiter._storage.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter._storage.reset()


def _mock_card_lookup(monkeypatch):
    # The route only calls read_card_by_token(token) and 404s on None: stub it so the test
    # never touches Supabase and is fast (the rate limit fires regardless of the route result).
    monkeypatch.setattr("app.routes.cards.cards_service.read_card_by_token", lambda token: None)


def test_public_card_read_blocks_the_21st_request_from_one_ip(client, limited, monkeypatch):
    _mock_card_lookup(monkeypatch)
    headers = {"X-Forwarded-For": "11.11.11.11"}
    for i in range(20):  # the CARD_READ_LIMITS minute budget
        r = client.get("/api/v1/cards/anytoken", headers=headers)
        assert r.status_code == 404, f"request {i} should pass the limiter (got {r.status_code})"
    blocked = client.get("/api/v1/cards/anytoken", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many attempts. Please wait a moment and try again."}
    assert blocked.headers.get("Retry-After") == "60"


def test_a_different_ip_keeps_its_own_budget(client, limited, monkeypatch):
    _mock_card_lookup(monkeypatch)
    for _ in range(21):  # exhaust IP A
        client.get("/api/v1/cards/x", headers={"X-Forwarded-For": "22.22.22.22"})
    # IP B's first request is unaffected: the key isolates per IP (a shared NAT is safe).
    other = client.get("/api/v1/cards/x", headers={"X-Forwarded-For": "33.33.33.33"})
    assert other.status_code == 404


def test_a_normal_user_under_the_limit_is_never_429(client, limited, monkeypatch):
    _mock_card_lookup(monkeypatch)
    for _ in range(10):
        r = client.get("/api/v1/cards/x", headers={"X-Forwarded-For": "44.44.44.44"})
        assert r.status_code != 429


def test_the_global_default_throttles_even_an_undecorated_route(client, limited):
    # The "all API" guarantee: every route, even one with NO @limiter.limit (here /health),
    # inherits the 120/min global default via the middleware, so any endpoint is bounded.
    headers = {"X-Forwarded-For": "55.55.55.55"}
    for _ in range(120):
        assert client.get("/health", headers=headers).status_code == 200
    assert client.get("/health", headers=headers).status_code == 429
