"""Subscription data service (v3): the plan list, the caller's subscription, the webhook write.

The thin data layer behind the billing surface (Docs/FeatureDecisions.md, the
Subscription DEFER entry; HardRules/Api/Modules/Subscription.md). Three concerns, with
very different trust:

  - READ THE PLAN LIST (auth): list_plans(user). The price list the app shows. Reads
    public.plan_tier under the caller's token (read-for-authenticated reference data).

  - READ MY SUBSCRIPTION (auth): get_my_subscription(user). The caller's own tier +
    status + period end, RLS-scoped to auth.uid() (the subscription_select_own policy).
    A user who has never paid has no row, which reads as the free default.

  - APPLY A BILLING EVENT (NO Supabase session, webhook only): apply_event(event). The
    ONLY writer of subscription state. It runs the SECURITY DEFINER RPC
    public.apply_subscription_event (migration 0018) through the SERVICE-ROLE client, so
    it writes past RLS exactly as the billing webhook needs and as a user cannot. The RPC
    is idempotent on the Stripe event id (the billing_event ledger), so a replayed webhook
    is a safe no-op; apply_event returns whether the event was newly applied. The webhook
    authenticates by STRIPE SIGNATURE before this is ever reached (app/services/stripe_stub
    + app/routes/billing), never by a user session.

User scoping and RLS (HardRules/Api/Modules/Auth.md): the two reads run through
get_anon_client(user.access_token) so RLS scopes them to the caller. The write runs
through get_service_client() (RLS bypassed on purpose) and ONLY to call the narrow,
idempotent RPC, which is itself the boundary.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client, get_service_client
from app.models.subscription import MySubscription, PlanTier, SubscriptionEvent
from app.models.user_profile import SubscriptionTier
from app.services.pagination import MAX_BOUNDED_ROWS

logger = logging.getLogger(__name__)

PLAN_TIER_TABLE = "plan_tier"
SUBSCRIPTION_TABLE = "subscription"
APPLY_SUBSCRIPTION_EVENT_FN = "apply_subscription_event"


def _rows(response: Any) -> List[Dict[str, Any]]:
    data = getattr(response, "data", None)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def _first(response: Any) -> Optional[Dict[str, Any]]:
    rows = _rows(response)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# reads (auth, RLS-scoped)
# ---------------------------------------------------------------------------


def list_plans(user: AuthedUser) -> List[PlanTier]:
    """The active price list, ordered (free first), RLS-scoped read of plan_tier.

    plan_tier is read-for-authenticated reference data; this returns only the active tiers
    so a retired tier disappears from the app without deleting its historical subscriptions.
    Ordered by sort then key for a deterministic list.

    BOUNDED (the every-list-is-capped rule): there are only a few plan tiers (a fixed,
    curated price list), so the list needs no cursor; the read still carries a hard
    MAX_BOUNDED_ROWS `.limit(...)` so a pathological tier count can never make the query
    unbounded. The cap is far above any real tier count.
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PLAN_TIER_TABLE)
        .select("*")
        .eq("active", True)
        .order("sort")
        .limit(MAX_BOUNDED_ROWS)
        .execute()
    )
    return [PlanTier.model_validate(row) for row in rows]


def get_my_subscription(user: AuthedUser) -> MySubscription:
    """The caller's own subscription (RLS-scoped), or the free default if none exists yet.

    Reads subscription where user_id == auth.uid() (the subscription_select_own policy).
    A user who has never paid has no row, so this returns tier 'free', status 'none', no
    period end. The app shows this; the gate never trusts it (it re-resolves server-side).
    """
    client = get_anon_client(user.access_token)
    row = _first(
        client.table(SUBSCRIPTION_TABLE)
        .select("tier_key,status,current_period_end")
        .eq("user_id", user.id)
        .maybe_single()
        .execute()
    )
    if not row:
        return MySubscription(tier=SubscriptionTier.FREE, status="none", current_period_end=None)
    return MySubscription(
        tier=row.get("tier_key", SubscriptionTier.FREE.value),
        status=row.get("status", "none"),
        current_period_end=row.get("current_period_end"),
    )


# ---------------------------------------------------------------------------
# the webhook write path (NO Supabase session): the ONLY writer of subscription state
# ---------------------------------------------------------------------------


def apply_event(event: SubscriptionEvent) -> bool:
    """Apply a verified, normalised billing event: write subscription state via the RPC.

    The ONLY path that writes subscription state. It calls the SECURITY DEFINER function
    public.apply_subscription_event through the SERVICE-ROLE client (RLS bypassed on
    purpose), passing the event id, the resolved user_id, and the new tier/status/period/
    Stripe ids. The RPC is IDEMPOTENT: it records the event id in billing_event first and
    returns false WITHOUT touching the subscription if that id was already processed (Stripe
    delivers at least once), else upserts the row and returns true.

    Precondition: the caller (the billing webhook) has ALREADY verified the Stripe signature
    and mapped the Stripe object to event.user_id. This function does not authenticate; it
    writes the already-trusted event. Returns the RPC's boolean (True = newly applied,
    False = duplicate/no-op) so the route can report idempotent handling.
    """
    client = get_service_client()
    params = {
        "p_event_id": event.event_id,
        "p_user_id": event.user_id,
        "p_tier_key": event.tier_key.value
        if isinstance(event.tier_key, SubscriptionTier)
        else str(event.tier_key),
        "p_status": event.status,
        "p_current_period_end": (
            event.current_period_end.isoformat() if event.current_period_end else None
        ),
        "p_stripe_customer_id": event.stripe_customer_id,
        "p_stripe_subscription_id": event.stripe_subscription_id,
        "p_event_type": event.event_type,
    }
    response = client.rpc(APPLY_SUBSCRIPTION_EVENT_FN, params).execute()
    applied = getattr(response, "data", None)
    # The RPC returns a single boolean; supabase may wrap it as the .data value directly.
    if isinstance(applied, list):
        applied = applied[0] if applied else None
    return bool(applied)
