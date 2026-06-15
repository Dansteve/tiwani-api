"""The billing READ routes + the stubbed checkout (auth, RLS-scoped).

GET /api/v1/billing/plans and GET /api/v1/billing/me are the app's read surface (show the
price list + the caller's tier); POST /api/v1/billing/checkout is STUBBED (PENDING OWNER
STRIPE KEYS) and returns 503. All three require the Supabase current user (a user can SEE the
plans and their tier, and START a checkout, but never SET their tier). The reads are proven to
serialize the plan_tier / subscription rows; the gate is tested separately.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.services.subscription as sub_service
from app.auth import get_current_user
from app.models.subscription import MySubscription, PlanTier
from app.models.user_profile import SubscriptionTier
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


class _AuthedUser:
    id = "u-1"
    email = "ada@example.com"
    access_token = "tok-abc"


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: _AuthedUser()
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/billing/plans"),
        ("get", "/api/v1/billing/me"),
        ("post", "/api/v1/billing/checkout"),
    ],
)
def test_billing_routes_require_auth(client, method, path):
    if method == "get":
        response = client.get(path)
    else:
        response = client.post(path, json={"tier_key": "standard"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /billing/plans
# ---------------------------------------------------------------------------


def test_list_plans_returns_the_price_list(authed, monkeypatch):
    plans = [
        PlanTier(key=SubscriptionTier.FREE, name="Free", price_monthly_pence=0, sort=0),
        PlanTier(key=SubscriptionTier.STANDARD, name="Standard", price_monthly_pence=1999, sort=1),
        PlanTier(key=SubscriptionTier.PREMIUM, name="Premium", price_monthly_pence=2999, sort=2),
    ]
    monkeypatch.setattr(sub_service, "list_plans", lambda user: plans)

    response = authed.get("/api/v1/billing/plans")
    assert response.status_code == 200
    body = response.json()
    keys = [t["key"] for t in body["tiers"]]
    assert keys == ["free", "standard", "premium"]
    # Prices are integer pence, exactly as stored (money is never a float).
    by_key = {t["key"]: t for t in body["tiers"]}
    assert by_key["standard"]["price_monthly_pence"] == 1999
    assert by_key["premium"]["price_monthly_pence"] == 2999
    # The Stripe price ids are NOT in the response (a server-side detail).
    assert "stripe_price_id_monthly" not in by_key["standard"]


def test_service_list_plans_caps_the_read(monkeypatch):
    # BOUNDED (the every-list-is-capped rule): there are only a few plan tiers, but the
    # plan_tier read still carries a safety `.limit(...)` as the runaway-read backstop.
    from app.services.pagination import MAX_BOUNDED_ROWS

    rows = [
        {"key": "free", "name": "Free", "price_monthly_pence": 0, "active": True, "sort": 0},
        {"key": "standard", "name": "Std", "price_monthly_pence": 1999, "active": True, "sort": 1},
    ]
    fake = FakeClient({("plan_tier", "select"): FakeResponse(rows)})
    monkeypatch.setattr("app.services.subscription.get_anon_client", lambda token=None: fake)

    tiers = sub_service.list_plans(_AuthedUser())

    assert [t.key.value for t in tiers] == ["free", "standard"]
    plan_select = next(
        c for c in fake.calls if c["table"] == "plan_tier" and c["op"] == "select"
    )
    assert plan_select["limit"] == MAX_BOUNDED_ROWS


# ---------------------------------------------------------------------------
# GET /billing/me
# ---------------------------------------------------------------------------


def test_my_subscription_default_free(authed, monkeypatch):
    monkeypatch.setattr(
        sub_service, "get_my_subscription",
        lambda user: MySubscription(
            tier=SubscriptionTier.FREE, status="none", current_period_end=None
        ),
    )
    response = authed.get("/api/v1/billing/me")
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "free"
    assert body["status"] == "none"
    assert body["current_period_end"] is None


def test_my_subscription_paid(authed, monkeypatch):
    monkeypatch.setattr(
        sub_service, "get_my_subscription",
        lambda user: MySubscription(
            tier=SubscriptionTier.PREMIUM, status="active", current_period_end=NOW
        ),
    )
    response = authed.get("/api/v1/billing/me")
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "premium"
    assert body["status"] == "active"
    assert body["current_period_end"] is not None


# ---------------------------------------------------------------------------
# POST /billing/checkout: STUBBED -> 503 (PENDING OWNER STRIPE KEYS)
# ---------------------------------------------------------------------------


def test_checkout_is_503_until_stripe_configured(authed):
    # No Stripe account/keys yet: create_checkout_session raises StripeNotConfiguredError,
    # which the route maps to 503. The surface exists and behaves predictably before go-live.
    response = authed.post(
        "/api/v1/billing/checkout", json={"tier_key": "standard", "cadence": "monthly"}
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# N3 follow-up: the 503 body is GOVERNED, never the raw StripeNotConfiguredError text
# ---------------------------------------------------------------------------


def test_checkout_503_returns_governed_copy_not_the_raw_exception(authed):
    # The route used to return detail=str(exc), which leaked the env-key names and the stub
    # file path. It now returns the governed billing-error copy; the raw exception is logged.
    from app.engines.subscription import render_billing_error

    response = authed.post(
        "/api/v1/billing/checkout", json={"tier_key": "standard", "cadence": "monthly"}
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == render_billing_error("billing.not_configured")
    # None of the raw exception internals (env key names / the stub file path) leak.
    assert "STRIPE_SECRET_KEY" not in detail
    assert "stripe_stub" not in detail
    assert "PENDING OWNER STRIPE KEYS" not in detail


def test_webhook_503_returns_governed_copy_not_the_raw_exception(client):
    # The webhook is NOT behind Supabase auth (Stripe is not a logged-in user), so it is
    # driven off the bare client. With no keys, verify_and_parse_event raises
    # StripeNotConfiguredError -> 503 with the governed body, never the raw exception text.
    from app.engines.subscription import render_billing_error

    response = client.post(
        "/api/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == render_billing_error("billing.not_configured")
    assert "STRIPE_SECRET_KEY" not in detail
    assert "stripe_stub" not in detail
