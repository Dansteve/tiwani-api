"""Subscription paywall COPY (Docs/FeatureDecisions.md, the paywall-copy refinement).

The GOVERNED paywall / upgrade copy, built as a standalone module with a guard test,
exactly like the Erosion Alert copy (app/engines/alerts/). The subscription feature
itself is DEFERRED behind six hard preconditions and is NOT built here: there is no
tier table, no entitlement values, no gate, no route, and no Stripe. This package is
the one piece the refinement isolates as buildable and testable now: the strings and
the rule that they stay calm and capacity-framed.

Module file: HardRules/Api/Modules/Subscription.md.

Layout:
  copy.py   GOVERNED COPY: the paywall messages keyed by the concrete convenience
            entitlement keys (recipients.max, card.pdf_export, card.history_depth,
            themes) and tier (Basic/Standard/Premium). Strings only.
  guard.py  the paywall guard: REUSES the shared clinical word list and ADDS the
            three banned families the refinement names (child-protection framing,
            efficacy/outcome claims, guilt/urgency/scarcity); enforced at render time
            and by the permanent guard test.

The gate, the tier prices, the entitlement VALUES, the webhook, and the routes are the
DEFERRED subscription work, governed separately once the preconditions clear; this
package stays copy-only.
"""

from app.engines.subscription.copy import (
    SAFETY_NET_REASSURANCE,
    TIER_DISPLAY_NAMES,
    EntitlementKey,
    PaywallCopy,
    Tier,
    all_emitted_strings,
    render_paywall,
    tiers_for,
)
from app.engines.subscription.guard import (
    BANNED_FAMILIES,
    BANNED_PHRASES,
    CLINICAL_WORDS,
    EFFICACY_WORDS,
    PROTECTION_WORDS,
    URGENCY_WORDS,
    PaywallCopyError,
    assert_all_clean,
    assert_clean,
    find_banned_phrases,
)

__all__ = [
    # copy
    "EntitlementKey",
    "PaywallCopy",
    "Tier",
    "TIER_DISPLAY_NAMES",
    "SAFETY_NET_REASSURANCE",
    "all_emitted_strings",
    "render_paywall",
    "tiers_for",
    # guard
    "BANNED_FAMILIES",
    "BANNED_PHRASES",
    "CLINICAL_WORDS",
    "EFFICACY_WORDS",
    "PROTECTION_WORDS",
    "URGENCY_WORDS",
    "PaywallCopyError",
    "assert_all_clean",
    "assert_clean",
    "find_banned_phrases",
]
