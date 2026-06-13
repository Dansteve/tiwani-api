"""v1 billing + subscription routes.

Thin HTTP only (HardRules/Api/SETUP.md): parse, call the subscription service / the Stripe
seam, serialize. The surface behind the subscription feature (Docs/FeatureDecisions.md, the
Subscription DEFER entry; HardRules/Api/Modules/Subscription.md):

  GET  /api/v1/billing/plans     the price list (active tiers, prices in pence). Auth.
  GET  /api/v1/billing/me        the caller's own subscription (tier, status, period). Auth.
  POST /api/v1/billing/checkout  start a Stripe-hosted Checkout (STUBBED -> 503 until keys). Auth.
  POST /api/v1/billing/webhook   the Stripe webhook: signature-verified, idempotent. No auth.

THE TWO TRUST MODELS:
  - The reads + checkout require the Supabase current user (RLS-scoped). A user can SEE the
    plans and their own tier, and START a checkout, but can NEVER set their own tier (there
    is no write surface here, and the self-grant fix removed subscription_tier from the
    profile update; precondition 2).
  - The WEBHOOK is the ONLY writer of subscription state and authenticates by STRIPE
    SIGNATURE, not a Supabase session (precondition 3). It does NOT depend on get_current_user:
    Stripe is not a logged-in user. The signature check (stubbed, PENDING OWNER STRIPE KEYS)
    is the boundary; the write goes through the SECURITY DEFINER RPC, idempotent on the Stripe
    event id (precondition 4).

STUBBED (PENDING OWNER STRIPE KEYS): there is no Stripe account yet, so the live SDK calls
(signature verification + the checkout session) raise StripeNotConfiguredError, which these
routes map to 503. The shapes and the hardening are real; only the live SDK is deferred.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth import AuthedUser, get_current_user
from app.engines.subscription import render_billing_error
from app.models.subscription import MySubscription, PlanList
from app.services import stripe_stub
from app.services import subscription as subscription_service

logger = logging.getLogger(__name__)

router = APIRouter()

# The Stripe signature header name (the live SDK reads this exact header). Plumbed now so the
# webhook contract is complete; the stubbed verifier still receives it.
STRIPE_SIGNATURE_HEADER = "stripe-signature"


# ---------------------------------------------------------------------------
# reads (auth, RLS-scoped)
# ---------------------------------------------------------------------------


@router.get("/billing/plans", response_model=PlanList)
def list_plans(user: AuthedUser = Depends(get_current_user)) -> PlanList:
    """The active price list (free first). The app shows this; it never gates on it."""
    return PlanList(tiers=subscription_service.list_plans(user))


@router.get("/billing/me", response_model=MySubscription)
def my_subscription(user: AuthedUser = Depends(get_current_user)) -> MySubscription:
    """The caller's own subscription (tier, status, period end), RLS-scoped to the caller."""
    return subscription_service.get_my_subscription(user)


# ---------------------------------------------------------------------------
# checkout (auth) - STUBBED until Stripe keys exist
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    """Start a checkout for a tier + cadence. The tier/cadence are validated against the
    live plan_tier prices server-side (the stub does not yet)."""

    tier_key: str
    cadence: str = "monthly"


class CheckoutSession(BaseModel):
    """The checkout session response: the Stripe-hosted URL the app redirects to."""

    url: str


@router.post("/billing/checkout", response_model=CheckoutSession)
def create_checkout(
    payload: CheckoutRequest,
    user: AuthedUser = Depends(get_current_user),
) -> CheckoutSession:
    """Start a Stripe-hosted Checkout for the caller (PCI out of scope).

    STUBBED (PENDING OWNER STRIPE KEYS): with no Stripe account, this returns 503 via
    StripeNotConfiguredError. When the keys land, create_checkout_session returns a real
    session URL for the chosen tier's Stripe price.
    """
    try:
        url = stripe_stub.create_checkout_session(user.id, payload.tier_key, payload.cadence)
    except stripe_stub.StripeNotConfiguredError as exc:
        # GOVERNED, guarded copy (mirrors the sharing / subscription routes): the raw
        # StripeNotConfiguredError text names env keys + the stub file path, so it never
        # reaches the client. The real exception is logged for debugging.
        logger.exception("Checkout unavailable: Stripe is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=render_billing_error("billing.not_configured"),
        ) from exc
    return CheckoutSession(url=url)


# ---------------------------------------------------------------------------
# the Stripe webhook (NO Supabase auth): the ONLY writer of subscription state
# ---------------------------------------------------------------------------


class WebhookResult(BaseModel):
    """The webhook ack. received is always True on a handled event; applied is True when the
    event was newly written, False when it was a duplicate (idempotent no-op)."""

    received: bool
    applied: bool


@router.post("/billing/webhook", response_model=WebhookResult)
async def stripe_webhook(request: Request) -> WebhookResult:
    """Handle a Stripe webhook: verify the signature, then idempotently write subscription state.

    NOT authenticated by a Supabase session (precondition 3): Stripe is not a logged-in user.
    The trust boundary is the STRIPE SIGNATURE. Flow:
      1. read the raw body + the Stripe-Signature header,
      2. verify_and_parse_event() verifies the signature AND returns the normalised event,
         reading the Stripe objects as the source of truth (STUBBED, PENDING OWNER STRIPE KEYS),
      3. apply_event() writes through the SECURITY DEFINER RPC, which is IDEMPOTENT on the
         Stripe event id (a replay is a no-op; Stripe delivers at least once).

    Failures fail CLOSED: a bad/absent signature or an unconfigured Stripe surface returns
    400/503 and writes nothing, so subscription state is never moved by an unverified request.
    """
    payload = await request.body()
    signature = request.headers.get(STRIPE_SIGNATURE_HEADER)

    try:
        event = stripe_stub.verify_and_parse_event(payload, signature)
    except stripe_stub.StripeNotConfiguredError as exc:
        # No keys yet: cannot verify, so cannot process. Fail closed with 503. GOVERNED,
        # guarded copy (mirrors the checkout path): the raw exception text names env keys
        # + the stub file path, so it never reaches the caller. The real exception is logged.
        logger.exception("Webhook unavailable: Stripe is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=render_billing_error("billing.not_configured"),
        ) from exc
    except ValueError as exc:
        # The live verifier raises on a bad/forged signature: reject the request, write nothing.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        ) from exc

    applied = subscription_service.apply_event(event)
    return WebhookResult(received=True, applied=applied)
