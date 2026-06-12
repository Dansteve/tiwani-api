"""Stripe integration boundary, STUBBED (PENDING OWNER STRIPE KEYS).

There is NO Stripe account or keys yet (Docs/FeatureDecisions.md, the Subscription DEFER
entry: "STUB the live Stripe SDK calls, clearly marked PENDING OWNER STRIPE KEYS"). This
module is the single seam where the live Stripe SDK will plug in. Every function here is a
STUB that raises StripeNotConfiguredError until the owner provides the keys and the live SDK
is wired in; the shapes and the contract are real, so the webhook route, the idempotency
ledger, and the entitlement gate are all fully built and tested AROUND this seam.

What is real now (built + tested, independent of Stripe):
  - the webhook route, signature-header plumbing, and idempotency (the billing_event ledger),
  - the normalisation from a Stripe event to the internal SubscriptionEvent,
  - the SECURITY DEFINER write path and the entitlement gate.

What is stubbed (PENDING OWNER STRIPE KEYS):
  - verify_and_parse_event(): live signature verification (stripe.Webhook.construct_event)
    and the live event payload. The HARDENING is designed in (signature verification +
    Stripe-as-source-of-truth + idempotency); only the live SDK call is deferred.
  - create_checkout_session(): the Stripe-hosted Checkout session (keeps PCI out of scope).

When the keys arrive: set STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET + the plan_tier
stripe_price_id_* values, add the `stripe` dependency, and replace the stub bodies with the
SDK calls (the TODOs mark the exact spots). Nothing else changes: the route and the write
path already speak the real shapes.
"""

from __future__ import annotations

from typing import Optional

from app.models.subscription import SubscriptionEvent

# PENDING OWNER STRIPE KEYS. These config names are where the live keys will be read from
# (env, via app/config.py) once the owner creates the Stripe account. Listed here so the
# wiring point is unambiguous; they are NOT used while the module is stubbed.
STRIPE_SECRET_KEY_ENV = "STRIPE_SECRET_KEY"
STRIPE_WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"


class StripeNotConfiguredError(RuntimeError):
    """Raised by every stubbed Stripe call: there is no Stripe account/keys yet.

    The billing route maps this to 503 Service Unavailable with a clear "billing is not yet
    configured" message, so the surface exists and behaves predictably before go-live, and a
    caller is never told a checkout or webhook succeeded when Stripe is not wired in.
    """

    def __init__(self, what: str):
        super().__init__(
            f"{what} requires the live Stripe SDK + keys (PENDING OWNER STRIPE KEYS). "
            "Set STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET and wire the SDK at "
            "app/services/stripe_stub.py before enabling billing."
        )


def is_configured() -> bool:
    """Whether live Stripe is wired in. Always False while this module is the stub.

    The route checks this to return a clean 503 instead of attempting a stubbed call. When
    the SDK lands, this returns True iff the keys are present.
    """
    return False


def verify_and_parse_event(payload: bytes, signature_header: Optional[str]) -> SubscriptionEvent:
    """STUB: verify the Stripe signature and parse the event into a SubscriptionEvent.

    PENDING OWNER STRIPE KEYS. The LIVE implementation will:
      1. stripe.Webhook.construct_event(payload, signature_header, STRIPE_WEBHOOK_SECRET),
         which BOTH verifies the signature (rejecting a forged/replayed body) AND returns the
         parsed event, so an unsigned or mis-signed request never reaches the write path;
      2. read the relevant Stripe objects (subscription, customer) as the SOURCE OF TRUTH for
         tier/status/period_end (never trust client-asserted post-checkout state);
      3. map the Stripe customer/subscription to the local user_id and the tier_key (via the
         plan_tier.stripe_price_id_* mapping) and return a normalised SubscriptionEvent.

    Until then this raises StripeNotConfiguredError so the webhook cannot be processed without
    real signature verification (it fails CLOSED: no key, no processing).
    """
    # TODO(PENDING OWNER STRIPE KEYS): replace with stripe.Webhook.construct_event(...) +
    # the Stripe object reads + the user/tier mapping; return the normalised SubscriptionEvent.
    raise StripeNotConfiguredError("Verifying a Stripe webhook")


def create_checkout_session(user_id: str, tier_key: str, cadence: str) -> str:
    """STUB: create a Stripe-hosted Checkout session and return its URL.

    PENDING OWNER STRIPE KEYS. The LIVE implementation will create a Checkout Session for the
    chosen tier's Stripe Price (plan_tier.stripe_price_id_monthly / _yearly), tied to the
    user's Stripe customer, and return session.url for the app to redirect to. Stripe-hosted
    Checkout keeps card data off our servers (PCI out of scope). Until then this raises
    StripeNotConfiguredError (the route returns 503).
    """
    # TODO(PENDING OWNER STRIPE KEYS): replace with stripe.checkout.Session.create(...) and
    # return session.url. The price id comes from plan_tier, never hardcoded here.
    raise StripeNotConfiguredError("Creating a checkout session")
