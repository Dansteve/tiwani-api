"""Tests for the shared list-pagination helpers (the every-list-is-capped rule).

clamp_limit is the single definition of "the effective, safe page size" the growable
list services share (the /cards list keeps its own private clamp; new code uses this).
MAX_BOUNDED_ROWS is the safety cap a naturally bounded list hands to the database
`.limit(...)`. Both are pure, so they are pinned directly here.
"""

from __future__ import annotations

from app.services.pagination import MAX_BOUNDED_ROWS, clamp_limit


def test_clamp_limit_uses_default_when_unset():
    # None (a client omitting ?limit) falls back to the service's default.
    assert clamp_limit(None, default=50, maximum=100) == 50


def test_clamp_limit_uses_default_for_non_positive():
    # 0 and a negative both fall back to the default (a client can never ask for nothing).
    assert clamp_limit(0, default=50, maximum=100) == 50
    assert clamp_limit(-5, default=50, maximum=100) == 50


def test_clamp_limit_passes_a_value_within_range():
    # A legitimate value under the maximum is used as-is.
    assert clamp_limit(10, default=50, maximum=100) == 10


def test_clamp_limit_caps_at_the_maximum():
    # A value over the hard maximum is capped, so a client (or an internal caller) can never
    # make the database read an unbounded page (the cap is enforced here, not only at the route).
    assert clamp_limit(10_000, default=50, maximum=100) == 100
    assert clamp_limit(101, default=50, maximum=100) == 100


def test_clamp_limit_at_the_boundary_is_unchanged():
    # Exactly the maximum is allowed.
    assert clamp_limit(100, default=50, maximum=100) == 100


def test_max_bounded_rows_is_a_generous_safety_ceiling():
    # The bounded cap is a high ceiling: far above any legitimate roster / recipient /
    # alert / tier count, so it never truncates real data, only stops a runaway read.
    assert MAX_BOUNDED_ROWS >= 100
