"""The PERMANENT banned-phrase guard test for paywall / subscription COPY.

TIWANI is non-clinical infrastructure and a feature that protects a vulnerable person
must never be SOLD with fear, guilt, a clinical word, or an outcome claim
(Docs/FeatureDecisions.md, the Subscription paywall-copy refinement). This test mirrors
tests/test_engine_alerts_guard.py over the paywall copy: it asserts that NO emitted
paywall string, across every entitlement key and tier (each heading, body, cta, and
reassurance, plus the tier labels and the shared reassurance line), contains any banned
phrase from any of the four governed families:

  1. clinical          - the SHARED alert word list (one list, reused, not forked)
  2. child_protection  - "protect" / "keep [name] safe" / "safer" / "at risk"
  3. efficacy          - "better continuity" / "more stable" / "improve"
  4. urgency_scarcity  - "before it's too late" / countdowns / "you've reached your limit"

It is non-negotiable and permanent: if a future copy edit introduces one of these, this
test fails and the change does not ship. The same guard runs at render time
(app/engines/subscription/copy.py render_paywall calls assert_clean), so a violating
string cannot even leave the module; this test is the standing proof over the WHOLE
governed surface.
"""

from __future__ import annotations

import pytest

from app.engines.subscription import (
    BANNED_FAMILIES,
    BANNED_PHRASES,
    CLINICAL_WORDS,
    SAFETY_NET_REASSURANCE,
    EntitlementKey,
    PaywallCopyError,
    all_emitted_strings,
    find_banned_phrases,
    render_paywall,
    tiers_for,
)
from app.engines.subscription.guard import (
    EFFICACY_WORDS,
    PROTECTION_WORDS,
    URGENCY_WORDS,
    assert_clean,
)

# The exact governed banned families (Docs/FeatureDecisions.md, the refinement). Pinned
# here so a change to the lists is a visible, deliberate edit (and still must clear
# sign-off). The clinical family is intentionally NOT re-typed: it is the shared alert
# list, asserted-identical below, so the non-clinical bar stays one governed list.
EXPECTED_PROTECTION = (
    "protect",
    "keep them safe",
    "keep [name] safe",
    "keep your child safe",
    "safer",
    "at risk",
    "safeguard",
)
EXPECTED_EFFICACY = (
    "better continuity",
    "more stable",
    "more stability",
    "improve",
    "improved",
    "better outcome",
    "better results",
    "more effective",
)
EXPECTED_URGENCY = (
    "before it's too late",
    "before it is too late",
    "don't miss out",
    "do not miss out",
    "act now",
    "hurry",
    "last chance",
    "limited time",
    "offer ends",
    "countdown",
    "you've reached your limit",
    "you have reached your limit",
    "you've hit your limit",
    "running out",
)


def test_banned_family_lists_are_exactly_the_governed_set():
    assert tuple(PROTECTION_WORDS) == EXPECTED_PROTECTION
    assert tuple(EFFICACY_WORDS) == EXPECTED_EFFICACY
    assert tuple(URGENCY_WORDS) == EXPECTED_URGENCY


def test_the_four_families_are_named_and_complete():
    # Exactly the four families the refinement names, in order, and BANNED_PHRASES is
    # their flat union (so no family is silently dropped from the matched set).
    assert tuple(name for name, _ in BANNED_FAMILIES) == (
        "clinical",
        "child_protection",
        "efficacy",
        "urgency_scarcity",
    )
    flat = tuple(p for _f, words in BANNED_FAMILIES for p in words)
    assert BANNED_PHRASES == flat


def test_clinical_family_is_the_shared_alert_list_not_a_fork():
    # The clinical bar must be ONE governed list across the product. The paywall guard
    # reuses the alert guard's list; assert they are byte-identical so a fork can never
    # drift the two apart.
    from app.engines.alerts.guard import PROHIBITED_WORDS as ALERT_CLINICAL

    assert tuple(CLINICAL_WORDS) == tuple(ALERT_CLINICAL)


def test_no_emitted_paywall_string_contains_a_banned_phrase():
    # The whole governed surface: every key x tier message (heading/body/cta/
    # reassurance), the tier labels, and the shared reassurance line.
    offenders = {
        string: find_banned_phrases(string)
        for string in all_emitted_strings()
        if find_banned_phrases(string)
    }
    assert offenders == {}, f"banned phrases found in paywall copy: {offenders}"


def test_every_rendered_paywall_passes_the_guard_at_emit_time():
    # render_paywall runs assert_clean internally; if any key/tier produced a banned
    # phrase it would raise here. Covers every defined (key, tier) message.
    for key in EntitlementKey:
        for tier in tiers_for(key):
            render_paywall(key, tier)  # must not raise


@pytest.mark.parametrize("phrase", BANNED_PHRASES)
def test_each_banned_phrase_is_actually_caught_by_the_guard(phrase):
    # The guard is not vacuous: a string containing each banned phrase is rejected,
    # case-insensitively, across all four families.
    assert find_banned_phrases(f"This mentions {phrase.upper()} explicitly.") != []
    with pytest.raises(PaywallCopyError):
        assert_clean(f"contains {phrase} here")


def test_a_banned_phrase_from_each_family_is_caught_with_its_family_label():
    # One representative phrase per family is caught AND reported under the right family,
    # so a violation points at which constraint it broke.
    assert find_banned_phrases("clinical care plan") == [("clinical", "clinical")]
    assert find_banned_phrases("we protect your child") == [
        ("child_protection", "protect")
    ]
    assert find_banned_phrases("better continuity for the family") == [
        ("efficacy", "better continuity")
    ]
    assert find_banned_phrases("upgrade before it's too late") == [
        ("urgency_scarcity", "before it's too late")
    ]


def test_clean_capacity_framed_text_passes_the_guard():
    # The capacity-framed register the refinement endorses passes cleanly.
    assert find_banned_phrases(
        "Basic covers two care recipients in full. Standard covers up to three."
    ) == []
    assert_clean(
        "Add a third care recipient",
        "See the Standard plan",
        SAFETY_NET_REASSURANCE,
    )  # must not raise


def test_the_recipient_paywall_states_two_free_then_offers_the_next_tier():
    # Guard against a vacuous pass: the headline recipients message must actually carry
    # the capacity framing (two covered free) and an onward, pressure-free step, not be
    # empty. (A content check, kept minimal: the exact wording is governed copy.)
    copy = render_paywall(EntitlementKey.RECIPIENTS_MAX, "standard")
    assert "two" in copy.body.lower()
    assert "three" in copy.body.lower()
    # The reassurance restates the tier-invariant safety net on every message.
    assert copy.reassurance == SAFETY_NET_REASSURANCE
    assert "free" in copy.reassurance.lower()
