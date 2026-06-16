"""Table-driven test for the deterministic ENGAGEMENT band (owner-track Task 12).

The engagement band (the owner's "disengagement" Tier-1 idea, the researcher + psychiatrist
boards' HONEST shape) classifies a chapter into NOT_STARTED / ACTIVE / QUIET / RESTING from
ONE fact: whole weeks since the most recent PREPARED activity. The week thresholds are
PRODUCT-OWNER numbers (ACTIVE_MAX_WEEKS = 4, QUIET_MAX_WEEKS = 8); this test pins them at the
boundaries so the same history always yields the same band, and pins the MANDATORY
was-active-then-quiet guard (zero lifetime activity is NOT_STARTED, never quiet/resting).

A fixed `now` is threaded into band() so the boundaries are exact and the test never reads the
real clock (the engine is deterministic, no clock inside scoring).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.engines.engagement import (
    ACTIVE_MAX_WEEKS,
    QUIET_MAX_WEEKS,
    EngagementBand,
    band,
    weeks_since,
)

# A fixed reference instant so every boundary below is exact (no real-clock flake).
NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


def prepared_weeks_ago(weeks: int, days: int = 0) -> str:
    """An ISO timestamp `weeks` weeks (plus optional days) before NOW, as the wire string."""
    return (NOW - timedelta(weeks=weeks, days=days)).isoformat()


def test_the_week_constants_are_the_product_owner_numbers():
    # The thresholds are owner numbers; pin them so a change is a deliberate, visible edit.
    assert ACTIVE_MAX_WEEKS == 4
    assert QUIET_MAX_WEEKS == 8


# ---------------------------------------------------------------------------
# The was-active-then-quiet GUARD (mandatory): zero lifetime activity is NOT_STARTED
# ---------------------------------------------------------------------------


def test_zero_activity_is_not_started_never_quiet_or_resting():
    # You cannot abandon what you never began: a chapter with NO prepared activity is the
    # existing grey NOT_STARTED, whatever the (absent) timestamp. The quiet/resting bands are
    # unreachable for it. This is the boards' mandatory guard.
    assert band(last_prepared_at=None, activity_count=0, now=NOW) == EngagementBand.NOT_STARTED


def test_zero_activity_with_a_stray_old_timestamp_is_still_not_started():
    # Defensive: even if a stray old timestamp were present, a zero count means never-active,
    # so the guard still returns NOT_STARTED (the count is the authority on was-it-ever-active).
    stale = prepared_weeks_ago(40)
    assert band(last_prepared_at=stale, activity_count=0, now=NOW) == EngagementBand.NOT_STARTED


def test_a_counted_activity_with_no_parseable_timestamp_is_not_started():
    # A count but no measurable last_prepared_at: we cannot measure a gap, so we do NOT invent
    # a quiet/resting band; it falls back to NOT_STARTED's no-extra-signal behaviour.
    assert band(last_prepared_at=None, activity_count=3, now=NOW) == EngagementBand.NOT_STARTED
    assert band(last_prepared_at="not-a-timestamp", activity_count=3, now=NOW) == (
        EngagementBand.NOT_STARTED
    )


# ---------------------------------------------------------------------------
# The band boundaries (the PRODUCT-OWNER week numbers), for a once-active chapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "weeks_ago, expected",
    [
        # ACTIVE: recent, weeks <= 4.
        (0, EngagementBand.ACTIVE),
        (1, EngagementBand.ACTIVE),
        (3, EngagementBand.ACTIVE),
        (4, EngagementBand.ACTIVE),  # exactly the active ceiling is still ACTIVE
        # QUIET: 4 < weeks <= 8.
        (5, EngagementBand.QUIET),  # just over the active ceiling
        (6, EngagementBand.QUIET),
        (7, EngagementBand.QUIET),
        (8, EngagementBand.QUIET),  # exactly the quiet ceiling is still QUIET
        # RESTING: weeks > 8.
        (9, EngagementBand.RESTING),  # just over the quiet ceiling
        (12, EngagementBand.RESTING),
        (52, EngagementBand.RESTING),
    ],
)
def test_band_boundaries_for_a_once_active_chapter(weeks_ago, expected):
    # A once-active chapter (activity_count >= 1) is binned by whole weeks since the last
    # prepared activity, at the exact owner thresholds (4 and 8). The +1 activity makes the
    # guard pass so the time bands are reachable.
    assert band(prepared_weeks_ago(weeks_ago), activity_count=1, now=NOW) == expected


def test_the_active_quiet_boundary_is_at_the_start_of_week_five():
    # Whole-week flooring: any gap that still floors to 4 weeks is ACTIVE (the active ceiling is
    # inclusive at 4). The band only tips to QUIET once the gap reaches a FULL 5 weeks (35 days),
    # i.e. 4 weeks + 6 days is still week 4 (ACTIVE), and 4 weeks + 7 days = week 5 (QUIET).
    assert band(prepared_weeks_ago(4, days=0), activity_count=1, now=NOW) == EngagementBand.ACTIVE
    assert band(prepared_weeks_ago(4, days=6), activity_count=1, now=NOW) == EngagementBand.ACTIVE
    assert band(prepared_weeks_ago(5, days=0), activity_count=1, now=NOW) == EngagementBand.QUIET


def test_the_quiet_resting_boundary_is_at_the_start_of_week_nine():
    # The quiet ceiling is inclusive at 8 weeks; the band tips to RESTING only at a FULL 9 weeks
    # (63 days). So 8 weeks + 6 days is still week 8 (QUIET), and 9 weeks = week 9 (RESTING).
    assert band(prepared_weeks_ago(8, days=0), activity_count=1, now=NOW) == EngagementBand.QUIET
    assert band(prepared_weeks_ago(8, days=6), activity_count=1, now=NOW) == EngagementBand.QUIET
    assert band(prepared_weeks_ago(9, days=0), activity_count=1, now=NOW) == EngagementBand.RESTING


def test_band_is_deterministic_same_inputs_same_band():
    # The engine is deterministic (no AI, no randomness): the same inputs always yield the same
    # band, regardless of how many times it is called.
    ts = prepared_weeks_ago(6)
    first = band(ts, activity_count=2, now=NOW)
    for _ in range(5):
        assert band(ts, activity_count=2, now=NOW) == first
    assert first == EngagementBand.QUIET


def test_a_future_timestamp_is_treated_as_just_prepared_not_negative():
    # Clock skew (last_prepared_at slightly in the future): 0 weeks, ACTIVE, never a negative
    # band that would crash the bin logic.
    future = (NOW + timedelta(days=2)).isoformat()
    assert weeks_since(future, now=NOW) == 0
    assert band(future, activity_count=1, now=NOW) == EngagementBand.ACTIVE


def test_weeks_since_uses_the_supabase_parser_for_odd_timestamps():
    # The Py3.9 fractional-seconds trap: a trimmed-microsecond timestamp must still parse (via
    # parse_timestamptz), not silently become None and mis-band. ".21011" is 5 fractional
    # digits, which a naive fromisoformat rejects; the engine must handle it.
    odd = "2026-05-01T10:00:00.21011+00:00"  # ~6.5 weeks before NOW
    assert weeks_since(odd, now=NOW) is not None
    # And it bands as a real measurement (QUIET at ~6 to 7 weeks), not the unmeasurable fallback.
    assert band(odd, activity_count=1, now=NOW) == EngagementBand.QUIET
