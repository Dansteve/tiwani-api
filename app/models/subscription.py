"""Subscription + plan/entitlement response schemas (v3).

The cross-repo contract for the subscription surface (Docs/FeatureDecisions.md, the
Subscription DEFER entry; HardRules/Api/Modules/Subscription.md). These are pydantic
v2 schemas only: the tables, RLS, and the SECURITY DEFINER write path live in
migration 0014, the single source of schema truth. The authoritative gate is always
the server-side require_entitlement (app/services/entitlements.py); the app reads
these to SHOW the plan/price list and the caller's current tier, never to decide
access on its own.

  - PlanTier: one tier in the price list (GET /api/v3/billing/plans). Prices are in
    GBP pence (integer minor units), exactly as stored, so money is never a float.
  - MySubscription: the caller's own subscription state (GET /api/v3/billing/me):
    tier, status, period end. RLS-scoped to the caller.
  - SubscriptionEvent: the NORMALISED billing event the webhook hands to the service
    after it has verified the Stripe signature and mapped the Stripe object to a user.
    It is internal (not a client request body): the webhook builds it from the Stripe
    payload, then the service writes it through the SECURITY DEFINER RPC.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.user_profile import SubscriptionTier


class PlanTier(BaseModel):
    """One tier in the public price list (mirrors a public.plan_tier row).

    Prices are integer GBP pence (minor units) exactly as stored: free is 0, the paid
    tiers are their pence amount, and a null cadence (e.g. yearly, until the owner sets
    it) is None. The Stripe price ids are omitted from the response (a server-side
    detail the checkout path uses); the app needs only the human price to display.
    """

    model_config = ConfigDict(from_attributes=True)

    key: SubscriptionTier
    name: str
    price_monthly_pence: Optional[int] = None
    price_yearly_pence: Optional[int] = None
    active: bool = True
    sort: int = 0


class MySubscription(BaseModel):
    """The caller's own subscription state (RLS-scoped to auth.uid()).

    tier is the authoritative tier the gate resolves (subscription.tier_key, written
    only by the billing webhook); a user who has never paid resolves to 'free' with
    status 'none' and no period end. The app shows this; it does not gate on it.
    """

    tier: SubscriptionTier = SubscriptionTier.FREE
    status: str = "none"
    current_period_end: Optional[datetime] = None


class SubscriptionEvent(BaseModel):
    """The normalised billing event the webhook hands to the write path (INTERNAL).

    NOT a client request body: the billing webhook verifies the Stripe signature, reads
    the Stripe event, maps the Stripe customer/subscription to the local user_id (Stripe
    is the source of truth), and builds this. The service then applies it through the
    SECURITY DEFINER RPC apply_subscription_event, which is idempotent on event_id.
    """

    event_id: str
    event_type: Optional[str] = None
    user_id: str
    tier_key: SubscriptionTier
    status: str
    current_period_end: Optional[datetime] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None


class PlanList(BaseModel):
    """The price-list response wrapper (GET /api/v3/billing/plans)."""

    tiers: List[PlanTier]
