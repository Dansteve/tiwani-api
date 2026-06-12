"""The ONE entitlement gate, proven (Docs/FeatureDecisions.md, Subscription precondition 6).

The gate is ALLOWLIST-based, fails CLOSED, and is NEVER applied to a must-stay-free key.
This file pins all four properties against a fake Supabase client that actually filters the
seeded subscription / user_profile / feature_entitlement rows by the .eq predicates (so the
gate's real reads run), with the board split as the data:

  recipients.max  free=2 / standard=3 / premium=unlimited
  card.pdf_export free=false / standard=true / premium=true
  themes          free=false / standard=true / premium=true

No live Supabase (blocked in the sandbox; the task requires mocking). The filtering fake here
is the proof at the code layer; the real-Postgres RLS test proves the DB policies separately.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

import app.services.entitlements as ent
from app.auth import AuthedUser

USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# The board split as feature_entitlement rows.
ENTITLEMENT_ROWS = [
    {"feature_key": "recipients.max", "tier_key": "free", "value": "2"},
    {"feature_key": "recipients.max", "tier_key": "standard", "value": "3"},
    {"feature_key": "recipients.max", "tier_key": "premium", "value": "unlimited"},
    {"feature_key": "card.pdf_export", "tier_key": "free", "value": "false"},
    {"feature_key": "card.pdf_export", "tier_key": "standard", "value": "true"},
    {"feature_key": "card.pdf_export", "tier_key": "premium", "value": "true"},
    {"feature_key": "themes", "tier_key": "free", "value": "false"},
    {"feature_key": "themes", "tier_key": "standard", "value": "true"},
    {"feature_key": "themes", "tier_key": "premium", "value": "true"},
]


class _Resp:
    def __init__(self, data: Any):
        self.data = data


class _Query:
    """A fluent query that filters the backing rows by the recorded .eq predicates."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self._filters: List[Tuple[str, Any]] = []
        self._single = False

    def select(self, *a: Any, **k: Any) -> "_Query":
        return self

    def eq(self, col: str, val: Any) -> "_Query":
        self._filters.append((col, val))
        return self

    def maybe_single(self) -> "_Query":
        self._single = True
        return self

    def single(self) -> "_Query":
        self._single = True
        return self

    def execute(self) -> _Resp:
        matched = [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]
        if self._single:
            return _Resp(matched[0] if matched else None)
        return _Resp(matched)


class _Client:
    """A read-only fake whose table(name) filters that table's seeded rows."""

    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self._tables = tables

    def table(self, name: str) -> _Query:
        return _Query(self._tables.get(name, []))


def _make_client(tier_key: str | None, profile_tier: str | None = None):
    """A client whose subscription row has tier_key (or no row if None), plus the split."""
    subscription_rows = (
        [{"user_id": "u-1", "tier_key": tier_key, "status": "active"}] if tier_key else []
    )
    profile_rows = (
        [{"id": "u-1", "subscription_tier": profile_tier}] if profile_tier else []
    )
    return _Client(
        {
            "subscription": subscription_rows,
            "user_profile": profile_rows,
            "feature_entitlement": ENTITLEMENT_ROWS,
        }
    )


@pytest.fixture
def patch_client(monkeypatch):
    """Point the entitlement service's get_anon_client at the chosen fake."""

    def _install(tier_key, profile_tier=None):
        client = _make_client(tier_key, profile_tier)
        monkeypatch.setattr(ent, "get_anon_client", lambda token=None, _c=client: _c)
        return client

    return _install


# ---------------------------------------------------------------------------
# the must-stay-free red-line: the gate REFUSES to be called on a safety-net key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("free_key", sorted(ent.MUST_STAY_FREE))
def test_safety_net_key_is_never_gated(free_key, patch_client):
    # Calling the gate on a must-stay-free key is a programming/governance error, caught here.
    patch_client("free")
    with pytest.raises(ent.MustStayFreeError):
        ent.require_entitlement(USER, free_key)
    with pytest.raises(ent.MustStayFreeError):
        ent.require_feature(USER, free_key)
    with pytest.raises(ent.MustStayFreeError):
        ent.entitlement_limit(USER, free_key)
    with pytest.raises(ent.MustStayFreeError):
        ent.is_feature_gated(free_key)


def test_must_stay_free_and_gated_sets_are_disjoint():
    # The two governed sets must never overlap: a key cannot be both gated and safety-net.
    assert ent.GATED_FEATURES.isdisjoint(ent.MUST_STAY_FREE)


def test_safety_net_covers_every_board_named_surface():
    # The board's must-stay-free list, named as keys. If a future edit drops one, this fails.
    expected = {
        "plan.generate",
        "card.create",
        "card.share_link",
        "card.health_safety",
        "card.revoke",
        "alerts.evaluate",
        "lci.view",
        "pulse.record",
        "profile.manage",
        "account.export",
        "account.delete",
    }
    assert expected <= ent.MUST_STAY_FREE


# ---------------------------------------------------------------------------
# allowlist discipline: an un-allowlisted key is never gated (free by default)
# ---------------------------------------------------------------------------


def test_unknown_non_allowlisted_feature_is_free_by_default(patch_client):
    # A key that is neither allowlisted nor safety-net is simply NOT gated: a forgotten/new
    # feature is free until deliberately added to GATED_FEATURES (never silently paywalled).
    patch_client("free")
    assert ent.is_feature_gated("some.future.feature") is False
    assert ent.require_feature(USER, "some.future.feature") is True
    ent.require_entitlement(USER, "some.future.feature")  # must not raise
    assert ent.entitlement_limit(USER, "some.future.feature") is None  # uncapped


# ---------------------------------------------------------------------------
# a paid BOOL feature gates by tier (card.pdf_export, themes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("paid_key", ["card.pdf_export", "themes"])
def test_paid_bool_feature_denied_on_free_granted_on_paid(paid_key, patch_client):
    # free -> denied (fails the gate); standard/premium -> granted.
    patch_client("free")
    assert ent.require_feature(USER, paid_key) is False
    with pytest.raises(ent.EntitlementError):
        ent.require_entitlement(USER, paid_key)

    patch_client("standard")
    assert ent.require_feature(USER, paid_key) is True
    ent.require_entitlement(USER, paid_key)  # must not raise

    patch_client("premium")
    assert ent.require_feature(USER, paid_key) is True
    ent.require_entitlement(USER, paid_key)  # must not raise


# ---------------------------------------------------------------------------
# a paid INT feature gates by tier (recipients.max: 2 / 3 / unlimited)
# ---------------------------------------------------------------------------


def test_recipients_max_limit_per_tier(patch_client):
    patch_client("free")
    assert ent.entitlement_limit(USER, "recipients.max") == 2
    patch_client("standard")
    assert ent.entitlement_limit(USER, "recipients.max") == 3
    patch_client("premium")
    assert ent.entitlement_limit(USER, "recipients.max") is None  # unlimited


def test_recipients_max_free_covers_two_recipients(patch_client):
    # The board red-line: free covers TWO recipients in full. With 0 or 1 existing, creating
    # the next is allowed; at 2 the cap is reached.
    patch_client("free")
    ent.require_within_limit(USER, "recipients.max", 0)  # creating #1: ok
    ent.require_within_limit(USER, "recipients.max", 1)  # creating #2: ok
    with pytest.raises(ent.EntitlementError):
        ent.require_within_limit(USER, "recipients.max", 2)  # #3 blocked on free


def test_recipients_max_premium_is_unlimited(patch_client):
    patch_client("premium")
    # No cap: even a large existing count is allowed.
    ent.require_within_limit(USER, "recipients.max", 0)
    ent.require_within_limit(USER, "recipients.max", 99)


# ---------------------------------------------------------------------------
# fail CLOSED: unknown tier, missing row, no data -> deny a gated feature
# ---------------------------------------------------------------------------


def test_unknown_tier_fails_closed(patch_client):
    # A tier with no entitlement rows (an unexpected value) -> denied for a gated bool, and a
    # 0 cap (no headroom) for a gated int. The gate never grants on missing data.
    patch_client("enterprise")  # not a seeded tier
    assert ent.require_feature(USER, "card.pdf_export") is False
    with pytest.raises(ent.EntitlementError):
        ent.require_entitlement(USER, "themes")
    assert ent.entitlement_limit(USER, "recipients.max") == 0
    with pytest.raises(ent.EntitlementError):
        ent.require_within_limit(USER, "recipients.max", 0)


def test_no_subscription_row_falls_back_to_profile_then_free(patch_client):
    # No subscription row, but the profile says free -> resolves free (and the free split applies).
    patch_client(None, profile_tier="free")
    assert ent.resolve_tier(USER) == "free"
    assert ent.entitlement_limit(USER, "recipients.max") == 2

    # No subscription AND no profile tier -> defaults to free.
    patch_client(None, profile_tier=None)
    assert ent.resolve_tier(USER) == "free"
    assert ent.require_feature(USER, "card.pdf_export") is False


def test_subscription_tier_overrides_profile_tier(patch_client):
    # The authoritative tier is the subscription's (written only by the webhook). Even if the
    # profile still said free, a premium subscription row wins.
    patch_client("premium", profile_tier="free")
    assert ent.resolve_tier(USER) == "premium"
    assert ent.entitlement_limit(USER, "recipients.max") is None  # unlimited (premium)


def test_resolve_tier_fails_safe_to_free_when_subscription_read_errors(monkeypatch):
    # A transient billing-read error must never silently UPGRADE a user: resolve_tier falls
    # back, and with no readable data it defaults to the least-privilege 'free'.
    class _Boom:
        def table(self, name):
            raise RuntimeError("supabase blip")

    monkeypatch.setattr(ent, "get_anon_client", lambda token=None: _Boom())
    assert ent.resolve_tier(USER) == "free"
