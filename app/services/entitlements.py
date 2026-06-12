"""The ONE server-side entitlement gate (DB-driven, ALLOWLIST-based).

Backs the Subscription feature (Docs/FeatureDecisions.md, the Subscription DEFER
entry; HardRules/Api/Modules/Subscription.md). This module is the single place the
backend decides whether a caller's tier entitles them to a PAID feature. There is
no second gate: every paywalled affordance calls require_entitlement here.

The model, exactly per the board:

  - ALLOWLIST, never blocklist. We gate by ALLOWLISTING the PAID features
    (GATED_FEATURES). We NEVER blocklist the free ones: a forgotten blocklist entry
    would silently paywall the safety net. A feature that is not in GATED_FEATURES is
    simply not gated (require_feature returns true). So a new feature is free until it
    is deliberately added to the allowlist with a per-tier value.

  - The MUST-STAY-FREE red-line (precondition 6). The safety-net keys
    (MUST_STAY_FREE) are NEVER gated: plan generation, the Continuity Card + a share
    link + the health-and-safety line, all Erosion Alerts (L1/L2/L3), the LCI, the
    pulse, card revoke, profile management, and data export/delete. The gate REFUSES
    to be called on one of them: require_entitlement(user, a-must-stay-free-key)
    raises MustStayFreeError (a programming/governance error, caught by a test), so a
    safety-net feature can never accidentally be put behind the gate.

  - It FAILS CLOSED. For a gated feature, an unknown tier, a missing entitlement row,
    or an unreadable subscription resolves to DENY (require_feature returns false,
    require_entitlement raises EntitlementError). The default is "no access" unless the
    data positively grants it.

How tier is resolved: subscription.tier_key is authoritative (the billing webhook
writes it through the SECURITY DEFINER RPC, migration 0018). If there is no
subscription row yet (a user who has never paid), we fall back to
user_profile.subscription_tier, and finally to 'free'. Every read is RLS-scoped to
the caller (the subscription SELECT policy and the user_profile SELECT policy both
key on auth.uid()).

The value semantics per key (feature_entitlement.value is text so one column holds
all shapes):
  - a BOOL feature (card.pdf_export, themes): value 'true' grants, anything else denies.
  - an INT-or-unlimited feature (recipients.max): value 'unlimited' is no cap; an
    integer string is the cap. entitlement_limit() returns the int or None (unlimited);
    require_within_limit(used) enforces it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.models.user_profile import SubscriptionTier

logger = logging.getLogger(__name__)

SUBSCRIPTION_TABLE = "subscription"
USER_PROFILE_TABLE = "user_profile"
FEATURE_ENTITLEMENT_TABLE = "feature_entitlement"

# The sentinel an int-style entitlement uses for "no limit".
UNLIMITED = "unlimited"

# ---------------------------------------------------------------------------
# The governed key sets (the red-line, in code)
# ---------------------------------------------------------------------------

# The PAID features the gate enforces: the ALLOWLIST. A feature is gated ONLY if its key
# is here. Each key has a per-tier value in public.feature_entitlement (seeded by migration
# 0018 with the board split). Keys are enumerable and falsifiable, never vague "advanced":
#   recipients.max   how many care recipients a tier may have (2 / 3 / unlimited).
#   card.pdf_export  whether the tier can export a Continuity Card as a PDF (bool).
#   themes           whether the tier unlocks cosmetic themes (bool).
GATED_FEATURES: frozenset[str] = frozenset(
    {
        "recipients.max",
        "card.pdf_export",
        "themes",
    }
)

# The MUST-STAY-FREE safety net (Docs/FeatureDecisions.md red-line + Docs/Decisions.md).
# These features are NEVER gated, tier-invariant on every tier. The gate REFUSES to be
# called on one of them (require_entitlement raises MustStayFreeError), so the safety net
# can never be paywalled by a future edit. This frozenset is the enforced, tested red-line.
# Naming is by stable feature key (mirrors the surfaces the board listed):
MUST_STAY_FREE: frozenset[str] = frozenset(
    {
        "plan.generate",          # plan generation (the LCE)
        "card.create",            # the Continuity Card + a share link + the H&S line
        "card.share_link",        # at least one active share link per recipient
        "card.health_safety",     # the "if things get difficult" / health-and-safety line
        "card.revoke",            # revoking a shared card reaches every active token
        "alerts.evaluate",        # all Erosion Alerts L1/L2/L3 + their signposting
        "lci.view",               # the LCI / resilience signal
        "pulse.record",           # the post-activity pulse
        "profile.manage",         # profile + care-recipient management
        "account.export",         # data export (a data-portability right)
        "account.delete",         # account deletion
    }
)


class EntitlementError(PermissionError):
    """Raised when the caller's tier does NOT entitle them to a gated feature (route -> 402).

    A normal, expected outcome for a free user hitting a paid affordance (the route maps it
    to 402 Payment Required with governed copy). The gate fails CLOSED, so this is also what
    is raised when the entitlement data cannot be read or the tier is unknown.
    """

    def __init__(self, feature_key: str, tier: str):
        self.feature_key = feature_key
        self.tier = tier
        super().__init__(f"Tier '{tier}' is not entitled to feature '{feature_key}'")


class MustStayFreeError(RuntimeError):
    """Raised when the gate is called on a MUST_STAY_FREE key: a programming/governance bug.

    This is NEVER a user-facing error: it means a developer tried to gate a safety-net
    feature, which the red-line forbids. It fires loudly (and a guard test asserts it) so the
    mistake is caught in development, never shipped. The safety net is tier-invariant; it does
    not call the gate at all.
    """

    def __init__(self, feature_key: str):
        self.feature_key = feature_key
        super().__init__(
            f"Feature '{feature_key}' is in the must-stay-free safety net and must NEVER be "
            "gated (Docs/FeatureDecisions.md red-line). Do not call the entitlement gate on it."
        )


# ---------------------------------------------------------------------------
# tier resolution
# ---------------------------------------------------------------------------


def _first(response: Any) -> Optional[Dict[str, Any]]:
    data = getattr(response, "data", None)
    if data is None:
        return None
    if isinstance(data, list):
        return data[0] if data else None
    return data


def resolve_tier(user: AuthedUser) -> str:
    """Resolve the caller's authoritative tier key (RLS-scoped), defaulting to 'free'.

    subscription.tier_key is authoritative (written only by the billing webhook). If there
    is no subscription row yet, fall back to user_profile.subscription_tier, then to 'free'.
    Every read runs under the caller's token, so RLS makes another user's row unreachable.
    Fails to the SAFE default 'free' on any read error: a transient billing-read blip must
    never silently UPGRADE a user, and (because the gate fails closed) 'free' is the
    least-privilege answer.
    """
    client = get_anon_client(user.access_token)

    try:
        sub = _first(
            client.table(SUBSCRIPTION_TABLE)
            .select("tier_key,status")
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )
    except Exception:  # noqa: BLE001 - a billing read must never 500 a gated route; fall back.
        logger.warning("Could not read subscription.tier_key; falling back", exc_info=True)
        sub = None

    if sub and sub.get("tier_key"):
        return str(sub["tier_key"])

    # No subscription row yet: fall back to the profile's tier (server-owned), then 'free'.
    try:
        profile = _first(
            client.table(USER_PROFILE_TABLE)
            .select("subscription_tier")
            .eq("id", user.id)
            .maybe_single()
            .execute()
        )
    except Exception:  # noqa: BLE001 - same fail-safe default.
        logger.warning(
            "Could not read user_profile.subscription_tier; defaulting to free", exc_info=True
        )
        profile = None

    if profile and profile.get("subscription_tier"):
        return str(profile["subscription_tier"])
    return SubscriptionTier.FREE.value


def _entitlement_value(user: AuthedUser, feature_key: str, tier: str) -> Optional[str]:
    """The raw feature_entitlement.value for (feature_key, tier), or None if absent/unreadable.

    Read under the caller's token (feature_entitlement is read-for-authenticated reference
    data). None means "no row" (unknown tier or feature not configured for this tier), which
    the callers treat as fail-closed.
    """
    client = get_anon_client(user.access_token)
    try:
        row = _first(
            client.table(FEATURE_ENTITLEMENT_TABLE)
            .select("value")
            .eq("feature_key", feature_key)
            .eq("tier_key", tier)
            .maybe_single()
            .execute()
        )
    except Exception:  # noqa: BLE001 - unreadable entitlement -> fail closed (None).
        logger.warning(
            "Could not read feature_entitlement for %s/%s; failing closed", feature_key, tier,
            exc_info=True,
        )
        return None
    return row.get("value") if row else None


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def _guard_not_must_stay_free(feature_key: str) -> None:
    """Refuse to gate a must-stay-free key. The red-line, enforced at the call site."""
    if feature_key in MUST_STAY_FREE:
        raise MustStayFreeError(feature_key)


def is_feature_gated(feature_key: str) -> bool:
    """True if the feature is in the PAID allowlist (so the gate applies to it).

    A feature NOT in GATED_FEATURES is never gated (the allowlist discipline): callers of
    require_feature on an un-allowlisted key get a free pass (true). Raises MustStayFreeError
    if asked about a safety-net key (that key must never reach the gate at all).
    """
    _guard_not_must_stay_free(feature_key)
    return feature_key in GATED_FEATURES


def require_feature(user: AuthedUser, feature_key: str) -> bool:
    """Return True if the caller's tier is entitled to a BOOL feature; else False (fail closed).

    For a bool-style gated feature (card.pdf_export, themes): looks up the per-tier value and
    grants ONLY when it is exactly 'true'. A feature not in the allowlist is ungated -> True.
    A must-stay-free key raises MustStayFreeError (it must never be gated). Any missing row /
    unknown tier / read error -> False (fail closed).
    """
    _guard_not_must_stay_free(feature_key)
    if feature_key not in GATED_FEATURES:
        return True
    tier = resolve_tier(user)
    value = _entitlement_value(user, feature_key, tier)
    return value is not None and value.strip().lower() == "true"


def require_entitlement(user: AuthedUser, feature_key: str) -> None:
    """The ONE gate the routes call: raise EntitlementError unless the caller is entitled.

    For a bool-style PAID feature. Raises:
      - MustStayFreeError if the key is a safety-net key (a programming bug; must never gate it).
      - EntitlementError if the caller's tier is not entitled (the route maps it to 402),
        which is also what happens on any fail-closed path (missing data, unknown tier, error).
    Returns None (allow) when the feature is ungated or the tier is entitled.
    """
    _guard_not_must_stay_free(feature_key)
    if not require_feature(user, feature_key):
        raise EntitlementError(feature_key, resolve_tier(user))


def entitlement_limit(user: AuthedUser, feature_key: str) -> Optional[int]:
    """The integer cap for an INT-style gated feature (recipients.max), or None for unlimited.

    Returns:
      - None when the tier's value is 'unlimited' (no cap), OR (fail-closed nuance) when the
        feature is NOT in the allowlist (an ungated count is uncapped).
      - the integer cap otherwise.
      - 0 when the value is missing / unreadable / unparseable for a GATED feature: fail
        closed to the most restrictive cap (no headroom) rather than silently granting more.
    A must-stay-free key raises MustStayFreeError.
    """
    _guard_not_must_stay_free(feature_key)
    if feature_key not in GATED_FEATURES:
        return None  # not gated: uncapped
    tier = resolve_tier(user)
    value = _entitlement_value(user, feature_key, tier)
    if value is None:
        return 0  # fail closed: no row -> no headroom
    cleaned = value.strip().lower()
    if cleaned == UNLIMITED:
        return None
    try:
        return int(cleaned)
    except ValueError:
        logger.warning(
            "Unparseable limit '%s' for %s/%s; failing closed to 0", value, feature_key, tier
        )
        return 0


def require_within_limit(user: AuthedUser, feature_key: str, used: int) -> None:
    """Raise EntitlementError if `used` would meet/exceed the tier's cap for an INT feature.

    The check a count-limited paid feature uses (e.g. before creating an Nth care recipient:
    require_within_limit(user, "recipients.max", current_count)). Allowed when the cap is
    None (unlimited) or `used` is strictly below the cap; otherwise EntitlementError (402).
    Fails closed (cap 0 from a missing/bad row blocks). A must-stay-free key raises
    MustStayFreeError.
    """
    cap = entitlement_limit(user, feature_key)
    if cap is None:
        return
    if used >= cap:
        raise EntitlementError(feature_key, resolve_tier(user))
