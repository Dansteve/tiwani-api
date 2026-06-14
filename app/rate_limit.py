"""Application-wide rate limiting (Product.md section 5 + the 2026-06-13 board spec).

The api had NO throttle, so the public Continuity Card read, the invite redeem, and the
mint routes were a brute-force / guessable-short-code / spam surface (OWASP API4:2023).
This adds slowapi in two layers:
  - a GENEROUS global default on EVERY route (a safety net: a new route is throttled by
    default, and the free-tier instance is protected on any endpoint),
  - STRICT limits on the sensitive routes (redeem, the public card read, the mints) on top.

Keying: per client IP for unauthenticated routes (X-Forwarded-For aware, since the api sits
behind the Render / Cloud Run proxy, so the socket is the load balancer, not the client);
per bearer TOKEN for authenticated routes (an account-grade key that does not need the user
dependency, which the limiter runs too early to see). The store is in-process (memory://) by
default, correct for the single warm Render instance; the moment the api autoscales past one
instance the per-IP limit is fiction and RATE_LIMIT_STORAGE_URI must point at a shared Redis.
"""
import hashlib

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings


def client_ip(request: Request) -> str:
    """The real client IP, edge-enforced, never a client-forgeable value.

    The prod path is behind Cloudflare AND the Render / Cloud Run load balancer (two hops), so
    prefer CF-Connecting-IP (Cloudflare sets it at the edge; a client cannot forge it). Else the
    RIGHTMOST X-Forwarded-For entry, which our trusted proxy appended, NOT the leftmost (which is
    whatever the client typed, so evadable + a victim-lockout vector). Else the socket. If the
    deploy ever fronts the api without Cloudflare or with more trusted hops, restrict trust at the
    edge (uvicorn --proxy-headers --forwarded-allow-ips, or a Cloudflare-CIDR allowlist on CF-IP).
    """
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]  # rightmost: written by our trusted proxy, not client-forgeable
    return get_remote_address(request)


def token_key(request: Request) -> str:
    """A per-bearer-token key for authenticated routes (an account-grade throttle without
    resolving the user, which the limiter runs too early to see). Falls back to the client
    IP for an unauthenticated request. The token is hashed, never stored or logged.
    """
    auth = request.headers.get("authorization", "")
    if auth:
        return "tok:" + hashlib.sha256(auth.encode("utf-8")).hexdigest()[:24]
    return client_ip(request)


# The single app limiter. default_limits apply to EVERY route (the global safety net); the
# per-route @limiter.limit decorators add the strict limits on top. headers_enabled is OFF on
# purpose: with it ON, slowapi injects X-RateLimit-* into the route's RETURN value, which 500s a
# route that returns a Pydantic model with no `response` param (the card / redeem / mint happy
# path). The Retry-After on the governed 429 carries the only client-actionable hint we need.
limiter = Limiter(
    key_func=client_ip,
    default_limits=["120/minute"],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    headers_enabled=False,
)

# The strict per-route limits, named so the routes and the tests share one source of truth.
REDEEM_LIMITS = "5/minute;30/hour"        # the invite-redeem brute-force surface (per IP)
REDEEM_TOKEN_LIMIT = "20/minute"          # plus a per-token cap (a signed-in attacker)
CARD_READ_LIMITS = "20/minute;200/hour"   # the only anonymous bearer route (per IP)
MINT_LIMIT = "20/hour"                    # invite / need mint (per token), caps spam


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """The governed 429: the same {"detail": ...} envelope the api uses, calm and
    non-clinical, with a Retry-After. It never leaks which limit tripped.
    """
    response = JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Please wait a moment and try again."},
    )
    response.headers["Retry-After"] = "60"
    return response
