"""The Stripe webhook write path, proven (Docs/FeatureDecisions.md, Subscription precondition 4).

The webhook is the ONLY writer of subscription state and authenticates by STRIPE SIGNATURE,
not a Supabase session. This file proves:
  - it FAILS CLOSED while Stripe is unconfigured (no keys -> 503, nothing written): a webhook
    cannot move subscription state without real signature verification;
  - the write goes through the SECURITY DEFINER RPC public.apply_subscription_event with the
    exact normalised params (the service-role client calls .rpc(...));
  - IDEMPOTENCY: the RPC's boolean (True = newly applied, False = duplicate) is surfaced as
    `applied`, so a replayed Stripe event is a safe no-op (Stripe delivers at least once);
  - the route is NOT behind the Supabase current-user dependency (Stripe is not a logged-in
    user), so it reaches the verifier with no Authorization header.

The live signature verification + the Stripe-object reads are STUBBED (PENDING OWNER STRIPE
KEYS): the tests drive the seam (stripe_stub.verify_and_parse_event) directly, which is
exactly where the live SDK plugs in, so the hardening and the write contract are fully
exercised around the stub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import app.routes.billing as billing_routes
import app.services.subscription as sub_service
from app.models.subscription import SubscriptionEvent

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# a fake service-role client that records the RPC call and scripts its boolean
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, data: Any):
        self.data = data


class _Rpc:
    def __init__(self, fn: str, params: Any, log: List[Dict[str, Any]], result: Any):
        self._fn = fn
        self._params = params
        self._log = log
        self._result = result

    def execute(self) -> _Resp:
        self._log.append({"fn": self._fn, "params": self._params})
        return _Resp(self._result)


class _ServiceClient:
    """Records .rpc(fn, params) and returns the scripted boolean as .data."""

    def __init__(self, result: Any):
        self._result = result
        self.calls: List[Dict[str, Any]] = []

    def rpc(self, fn: str, params: Any = None) -> _Rpc:
        return _Rpc(fn, params, self.calls, self._result)


def _event(event_id: str = "evt_1") -> SubscriptionEvent:
    return SubscriptionEvent(
        event_id=event_id,
        event_type="customer.subscription.updated",
        user_id="u-1",
        tier_key="premium",
        status="active",
        current_period_end=NOW,
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
    )


# ---------------------------------------------------------------------------
# apply_event: the RPC is called with the normalised params; the boolean is surfaced
# ---------------------------------------------------------------------------


def test_apply_event_calls_the_security_definer_rpc_with_normalised_params(monkeypatch):
    client = _ServiceClient(result=True)
    monkeypatch.setattr(sub_service, "get_service_client", lambda: client)

    applied = sub_service.apply_event(_event("evt_42"))

    assert applied is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["fn"] == "apply_subscription_event"
    params = call["params"]
    # The exact privileged-write contract: event id, resolved user, tier, status, period, ids.
    assert params["p_event_id"] == "evt_42"
    assert params["p_user_id"] == "u-1"
    assert params["p_tier_key"] == "premium"  # enum coerced to its string key
    assert params["p_status"] == "active"
    assert params["p_current_period_end"] == NOW.isoformat()
    assert params["p_stripe_customer_id"] == "cus_1"
    assert params["p_stripe_subscription_id"] == "sub_1"
    assert params["p_event_type"] == "customer.subscription.updated"


def test_apply_event_reports_duplicate_as_not_applied(monkeypatch):
    # The RPC returns false for an already-processed event id (idempotency via billing_event).
    client = _ServiceClient(result=False)
    monkeypatch.setattr(sub_service, "get_service_client", lambda: client)
    assert sub_service.apply_event(_event("evt_dupe")) is False


def test_apply_event_unwraps_a_list_wrapped_boolean(monkeypatch):
    # Some PostgREST shapes wrap a scalar function result in a list; apply_event unwraps it.
    client = _ServiceClient(result=[True])
    monkeypatch.setattr(sub_service, "get_service_client", lambda: client)
    assert sub_service.apply_event(_event()) is True


# ---------------------------------------------------------------------------
# the webhook route: fails closed while Stripe is unconfigured (the stub)
# ---------------------------------------------------------------------------


def test_webhook_fails_closed_when_stripe_unconfigured(client):
    # No keys yet: verify_and_parse_event raises StripeNotConfiguredError, the route returns
    # 503 and writes NOTHING. A webhook cannot move state without real signature verification.
    response = client.post(
        "/api/v1/billing/webhook",
        content=b'{"id":"evt_1"}',
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 503


def test_webhook_does_not_require_supabase_auth(client):
    # The webhook is NOT behind get_current_user (Stripe is not a logged-in user): with no
    # Authorization header it still reaches the verifier (and 503s on the stub), never a 401.
    response = client.post("/api/v1/billing/webhook", content=b"{}")
    assert response.status_code != 401
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# the webhook route end-to-end (simulating the future live verifier): verify -> idempotent write
# ---------------------------------------------------------------------------


def test_webhook_writes_via_rpc_and_reports_applied(client, monkeypatch):
    # Simulate the live path: the verifier returns a normalised event (this is what the SDK
    # call will do once keys exist), then the route applies it through the RPC. First delivery
    # is applied=True.
    monkeypatch.setattr(
        billing_routes.stripe_stub, "verify_and_parse_event",
        lambda payload, signature: _event("evt_live"),
    )
    rpc_client = _ServiceClient(result=True)
    monkeypatch.setattr(sub_service, "get_service_client", lambda: rpc_client)

    response = client.post(
        "/api/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=sig"},
    )
    assert response.status_code == 200
    assert response.json() == {"received": True, "applied": True}
    assert rpc_client.calls[0]["params"]["p_event_id"] == "evt_live"


def test_webhook_replay_is_idempotent_no_op(client, monkeypatch):
    # A redelivered event: the verifier returns the same event id, the RPC returns False
    # (already in billing_event), and the route reports applied=False (a safe no-op).
    monkeypatch.setattr(
        billing_routes.stripe_stub, "verify_and_parse_event",
        lambda payload, signature: _event("evt_replay"),
    )
    rpc_client = _ServiceClient(result=False)
    monkeypatch.setattr(sub_service, "get_service_client", lambda: rpc_client)

    response = client.post(
        "/api/v1/billing/webhook", content=b"{}", headers={"stripe-signature": "s"}
    )
    assert response.status_code == 200
    assert response.json() == {"received": True, "applied": False}


def test_webhook_rejects_a_bad_signature(client, monkeypatch):
    # The LIVE verifier raises ValueError on a forged/invalid signature; the route maps that to
    # 400 and writes nothing. (Simulated here by making the seam raise ValueError.)
    def _bad_sig(payload, signature):
        raise ValueError("invalid signature")

    monkeypatch.setattr(billing_routes.stripe_stub, "verify_and_parse_event", _bad_sig)
    # If the write were reached it would explode (no service client scripted), proving none ran.
    response = client.post(
        "/api/v1/billing/webhook", content=b"{}", headers={"stripe-signature": "bad"}
    )
    assert response.status_code == 400
