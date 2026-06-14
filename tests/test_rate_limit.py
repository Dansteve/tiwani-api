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
from pydantic import BaseModel
from starlette.requests import Request

import main
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


# A decorated probe route returning a Pydantic model, registered once, to guard BLOCKER 1: with
# headers_enabled wrongly ON, slowapi injects X-RateLimit-* into the model return and 500s a route
# with no `response` param (the real card / redeem / mint happy path).
class _RlProbe(BaseModel):
    ok: bool


@main.app.get("/_rl_probe", response_model=_RlProbe)
@limiter.limit("5/minute")
def _rl_probe_route(request: Request) -> _RlProbe:
    return _RlProbe(ok=True)


# --- the key functions (pure) ---------------------------------------------------------------------

def test_client_ip_uses_the_rightmost_xff_not_the_forgeable_leftmost():
    # The trusted proxy APPENDS the real IP, so the rightmost entry is proxy-written; the
    # leftmost is whatever the client typed (evadable + a lockout vector). We key on the rightmost.
    req = make_request({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, client=("127.0.0.1", 1))
    assert client_ip(req) == "10.0.0.1"


def test_client_ip_prefers_cf_connecting_ip_over_xff():
    # The prod path is behind Cloudflare; CF-Connecting-IP is edge-set and not client-forgeable.
    req = make_request({"cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "forged, 2.2.2.2"})
    assert client_ip(req) == "1.1.1.1"


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


def test_a_decorated_route_returning_a_model_does_not_500_under_the_limiter(client, limited):
    # BLOCKER guard: headers_enabled=True made slowapi inject headers into a model return -> a 500
    # on every SUCCESS (card / redeem / mint). With it off, a decorated model route 200s.
    r = client.get("/_rl_probe", headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 200, f"decorated model route 500'd under the limiter ({r.status_code})"
    assert r.json() == {"ok": True}


def test_a_forged_rotating_leftmost_xff_does_not_get_a_fresh_budget(client, limited, monkeypatch):
    # BLOCKER guard: rotating the LEFTMOST X-Forwarded-For must NOT evade the per-IP limit. We
    # key on the rightmost (proxy-written), so a constant rightmost is one budget; the 21st is 429.
    _mock_card_lookup(monkeypatch)
    for i in range(20):
        h = {"X-Forwarded-For": f"66.66.{i}.{i}, 10.0.0.9"}  # forged leftmost rotates
        assert client.get("/api/v1/cards/x", headers=h).status_code == 404
    last = {"X-Forwarded-For": "66.66.99.99, 10.0.0.9"}
    assert client.get("/api/v1/cards/x", headers=last).status_code == 429
