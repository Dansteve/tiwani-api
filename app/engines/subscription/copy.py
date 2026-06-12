"""GOVERNED COPY: the paywall / upgrade strings. Do not change without the product
owner AND the psychiatrist sign-off (Docs/FeatureDecisions.md, the Subscription
paywall-copy refinement).

The subscription feature is DEFERRED behind six hard preconditions, so nothing here
is wired to a tier table, an entitlement gate, a route, or Stripe yet (those land
only after the preconditions clear and after the multi-recipient go-live + waitlist
in the sequencing). This module is the ONE buildable, testable piece the refinement
isolates: the paywall copy as a governed module with a guard test, exactly as the
Erosion Alert copy is governed.

The tone is the model the refinement names: the calm, capacity-framed one-recipient
409 ("Only one care recipient is supported right now. Managing more than one is
coming soon."). Every string states a CAPACITY plainly and offers a next step; none
of it uses fear, guilt, urgency, scarcity, a clinical word, a child-protection frame,
or an efficacy/outcome claim. Every string passes the paywall guard
(app/engines/subscription/guard.py); render_* re-checks at emit time and the guard
test (tests/test_engine_subscription_guard.py) pins it over all copy.

WHAT IS, AND IS NOT, GATEABLE (from the same refinement, pinned so the copy can never
describe gating the safety net):
  - The full free safety net is TIER-INVARIANT per recipient: plan generation, the
    Continuity Card + at least one live share link + its health-and-safety line, ALL
    erosion alerts and their signposting, the LCI/resilience signal, the pulse, card
    revoke, profile management, and data export/deletion are NEVER gated, on any tier.
  - Free (Basic) covers TWO care recipients in full, NOT one.
  - Only CONVENIENCE axes are gateable, and they are the concrete enumerable keys
    below (no vague "advanced" / "raised limits"): recipients beyond the covered set,
    PDF export, archived card-history depth, and cosmetic themes.

This module holds STRINGS only. It defines no tier prices, no entitlement values, and
no gate; those are the DEFERRED subscription work. The tier and key NAMES here are the
copy's own enumeration so the strings can be addressed and tested, not a live schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from app.engines.subscription.guard import assert_clean


class Tier(str, Enum):
    """The three tier names the copy addresses (owner-directed shape, Q3).

    BASIC is the free tier (the full safety net for two care recipients). STANDARD and
    PREMIUM are the paid convenience tiers. These are the copy's labels, NOT a live
    plan_tier table (that is the deferred subscription work); they exist so a paywall
    string can be keyed to a tier and pinned by a test.
    """

    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"


# Human tier labels the copy shows. Kept here so the wire/code keys (Tier values) stay
# stable and the display text lives in one place (the CHAPTER_DISPLAY_NAMES pattern).
TIER_DISPLAY_NAMES: Dict[Tier, str] = {
    Tier.BASIC: "Basic",
    Tier.STANDARD: "Standard",
    Tier.PREMIUM: "Premium",
}


class EntitlementKey(str, Enum):
    """The CONCRETE convenience-only entitlement keys the paywall copy describes.

    These are exactly the enumerable keys the refinement mandates in place of vague
    "advanced" / "raised soft limits": each is a falsifiable convenience axis. They are
    the copy's keys (the strings below are addressed by them); the live per-tier VALUES
    + the gate are the deferred subscription work, governed separately. NONE of these
    is the safety net: the safety net is tier-invariant and is never a gateable key.
    """

    RECIPIENTS_MAX = "recipients.max"  # how many care recipients a tier covers
    CARD_PDF_EXPORT = "card.pdf_export"  # download the card as a PDF (the web card is free)
    CARD_HISTORY_DEPTH = "card.history_depth"  # how far back the card history list reaches
    THEMES = "themes"  # cosmetic appearance themes


@dataclass(frozen=True)
class PaywallCopy:
    """One governed paywall message for a convenience entitlement at a tier.

    `key` is the convenience axis this message is about; `tier` is the tier that would
    unlock it; `heading` is the short calm title; `body` states the current capacity
    and the next step (capacity-framed, no pressure); `cta` is the action label;
    `reassurance` restates that the safety net is unaffected. All five are guarded.
    """

    key: EntitlementKey
    tier: Tier
    heading: str
    body: str
    cta: str
    reassurance: str


# The single reassurance line reused across every paywall message: it restates, in calm
# language, that nothing about the care recipient's safety net depends on upgrading. It
# is the spine of the capacity-framed tone (the refinement's hard line that the safety
# net is tier-invariant), and it carries no efficacy claim about what an upgrade does.
SAFETY_NET_REASSURANCE = (
    "Every care recipient keeps the full free TIWANI on any plan: their preparation "
    "plans, their Continuity Card and its share link, their alerts and signposting, "
    "and your data export. Upgrading only adds convenience."
)


# --- the governed paywall messages, by entitlement key ------------------------------
# Each states a plain capacity ("Basic covers two care recipients") and a plain next
# step ("Standard covers up to three"), in the calm 409 register. No fear, no guilt, no
# urgency, no scarcity, no clinical word, no child-protection frame, no efficacy claim.

# recipients.max: the headline convenience. Basic = two in full; Standard = up to three;
# Premium = no limit. Framed as capacity, never "pay to add your second child" (the free
# tier already covers two in full, which this copy states first).
_RECIPIENTS: Dict[Tier, PaywallCopy] = {
    Tier.STANDARD: PaywallCopy(
        key=EntitlementKey.RECIPIENTS_MAX,
        tier=Tier.STANDARD,
        heading="Add a third care recipient",
        body=(
            "Basic covers two care recipients in full. To manage a third, the Standard "
            "plan covers up to three. You can move to Standard whenever it suits you."
        ),
        cta="See the Standard plan",
        reassurance=SAFETY_NET_REASSURANCE,
    ),
    Tier.PREMIUM: PaywallCopy(
        key=EntitlementKey.RECIPIENTS_MAX,
        tier=Tier.PREMIUM,
        heading="Manage more care recipients",
        body=(
            "Standard covers up to three care recipients. The Premium plan removes the "
            "limit, for families caring for several people. You can move up whenever it "
            "suits you."
        ),
        cta="See the Premium plan",
        reassurance=SAFETY_NET_REASSURANCE,
    ),
}

# card.pdf_export: a convenience over the free, printable web card. The copy makes the
# free path explicit (the web card prints, with its full health-and-safety line), so no
# one reads PDF gating as withholding the safety content.
_CARD_PDF: Dict[Tier, PaywallCopy] = {
    Tier.STANDARD: PaywallCopy(
        key=EntitlementKey.CARD_PDF_EXPORT,
        tier=Tier.STANDARD,
        heading="Download the card as a PDF",
        body=(
            "The free Continuity Card opens in any browser and prints in full, including "
            "its health-and-safety details. A downloadable PDF file is part of the "
            "Standard plan, for sending or filing offline."
        ),
        cta="See the Standard plan",
        reassurance=SAFETY_NET_REASSURANCE,
    ),
}

# card.history_depth: the free history already shows every card with a live share link
# (the refinement's rule); the convenience is reaching FURTHER BACK into expired cards.
# Revoke reaches every card on every tier (stated, since revoke must stay free).
_CARD_HISTORY: Dict[Tier, PaywallCopy] = {
    Tier.STANDARD: PaywallCopy(
        key=EntitlementKey.CARD_HISTORY_DEPTH,
        tier=Tier.STANDARD,
        heading="See further back in your card history",
        body=(
            "Your free history always shows every card with a live share link, and you "
            "can revoke any card on any plan. A longer look back through older, expired "
            "cards is part of the Standard plan."
        ),
        cta="See the Standard plan",
        reassurance=SAFETY_NET_REASSURANCE,
    ),
}

# themes: purely cosmetic. The lightest convenience, framed as appearance only.
_THEMES: Dict[Tier, PaywallCopy] = {
    Tier.STANDARD: PaywallCopy(
        key=EntitlementKey.THEMES,
        tier=Tier.STANDARD,
        heading="Choose a different theme",
        body=(
            "TIWANI works exactly the same in its standard appearance. A choice of "
            "cosmetic themes is part of the Standard plan, if you would like to change "
            "how it looks."
        ),
        cta="See the Standard plan",
        reassurance=SAFETY_NET_REASSURANCE,
    ),
}

# The full registry: entitlement key -> {tier -> the governed message for unlocking it
# at that tier}. A key can have a message per tier that unlocks more of it (recipients
# has Standard and Premium; the others have a single Standard step today). The deferred
# gate, when built, reads its per-tier VALUES from a table; this registry is the COPY.
_PAYWALL_COPY: Dict[EntitlementKey, Dict[Tier, PaywallCopy]] = {
    EntitlementKey.RECIPIENTS_MAX: _RECIPIENTS,
    EntitlementKey.CARD_PDF_EXPORT: _CARD_PDF,
    EntitlementKey.CARD_HISTORY_DEPTH: _CARD_HISTORY,
    EntitlementKey.THEMES: _THEMES,
}


def _coerce_key(key: EntitlementKey | str) -> EntitlementKey:
    """Coerce an entitlement-key code or enum to the EntitlementKey enum."""
    return key if isinstance(key, EntitlementKey) else EntitlementKey(key)


def _coerce_tier(tier: Tier | str) -> Tier:
    """Coerce a tier code or enum to the Tier enum."""
    return tier if isinstance(tier, Tier) else Tier(tier)


def tiers_for(key: EntitlementKey | str) -> List[Tier]:
    """The tiers that have a governed paywall message for an entitlement key."""
    k = _coerce_key(key)
    return list(_PAYWALL_COPY[k].keys())


def render_paywall(key: EntitlementKey | str, tier: Tier | str) -> PaywallCopy:
    """The governed PaywallCopy for unlocking an entitlement key at a tier, guarded.

    Resolves the message for (key, tier), then runs the paywall guard over EVERY
    emitted string (heading, body, cta, reassurance) so a banned phrase can never
    leave the module. Raises KeyError if no message exists for that (key, tier) pair
    (a programming error: the caller asked for an undefined paywall), and
    PaywallCopyError if any string would violate the guard.
    """
    k = _coerce_key(key)
    t = _coerce_tier(tier)
    copy = _PAYWALL_COPY[k][t]
    assert_clean(copy.heading, copy.body, copy.cta, copy.reassurance)
    return copy


def all_emitted_strings() -> List[str]:
    """Every governed paywall string the module can emit, across all keys and tiers.

    The guard test iterates this to assert NO banned phrase appears anywhere: each
    message's heading, body, cta, and reassurance, plus the tier display names and the
    shared reassurance line. Keeping the enumeration here (next to the copy) means a new
    key, tier, or message is covered by the test automatically.
    """
    strings: List[str] = []
    for tier_messages in _PAYWALL_COPY.values():
        for copy in tier_messages.values():
            strings.extend([copy.heading, copy.body, copy.cta, copy.reassurance])
    strings.extend(TIER_DISPLAY_NAMES.values())
    strings.append(SAFETY_NET_REASSURANCE)
    return strings
