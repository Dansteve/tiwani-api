"""The deterministic ENGAGEMENT band for one Life Chapter (server-side, rules-based).

The engagement signal (the owner's "disengagement" Tier-1 idea, owner-track Task 12: "a
previously-active chapter going quiet (no activity for N weeks)"; the researcher +
psychiatrist boards' HONEST shape) classifies a chapter into a calm band from ONE fact: how
long it has been since the most recent PREPARED activity in that chapter (the
last_prepared_at the dashboard already computes). It is deterministic and rules-based (no AI,
no randomness, root CLAUDE.md): the same (last_prepared_at, activity_count, now) always
yields the same band.

THE WEEK NUMBERS ARE PRODUCT-OWNER NUMBERS. They live here as named constants (and are
pinned by a table-driven test) so the bands cannot drift silently:
  - active  (recent):       weeks_since_last_prepared <= ACTIVE_MAX_WEEKS (4)
  - quiet   (a while):       ACTIVE_MAX_WEEKS < weeks <= QUIET_MAX_WEEKS  (4 to 8)
  - resting (a long while):  weeks > QUIET_MAX_WEEKS                       (> 8)

THE WAS-ACTIVE-THEN-QUIET GUARD (mandatory, the boards' condition). A chapter with ZERO
lifetime prepared activities is the existing grey NOT_STARTED, NEVER quiet/resting: you
cannot abandon what you never began, and the dashboard already has an honest "Not started"
state for it (Product.md section 4.3). So band() returns NOT_STARTED whenever activity_count
is 0 (or there is no last_prepared_at to measure from); the quiet / resting bands are
reachable ONLY for a chapter that was once active. This guard is pinned by a test.

This module computes the BAND only (the enum). The governed user-facing copy for each band
lives in app/engines/engagement/copy.py, behind the guard; the OFF-by-default sign-off flag
lives in flag.py. Timestamp parsing goes through app.services.timestamps.parse_timestamptz
(the one correct Supabase-timestamp parser, the Py3.9 fractional-seconds trap).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.services.timestamps import parse_timestamptz

# PRODUCT-OWNER numbers (owner-track Task 12). A chapter prepared within ACTIVE_MAX_WEEKS is
# "active"; up to QUIET_MAX_WEEKS it is "quiet"; beyond that it is "resting". Whole weeks.
# Pinned by tests/test_engine_engagement_bands.py so a change is a deliberate, visible edit.
ACTIVE_MAX_WEEKS = 4
QUIET_MAX_WEEKS = 8

# Days per week, for the weeks-since computation (kept named, no magic number in the math).
_DAYS_PER_WEEK = 7


class EngagementBand(str, Enum):
    """The four engagement bands for a chapter (the string values are the wire codes).

    NOT_STARTED is the SAME state the dashboard paints grey for a chapter with no plan ever
    (Product.md section 4.3); the engagement signal never surfaces extra copy for it. ACTIVE
    is the healthy, recently-prepared state. QUIET and RESTING are the gentle "this chapter
    has gone a while without a plan" bands, reachable ONLY for a chapter that was once active
    (the was-active-then-quiet guard).
    """

    NOT_STARTED = "not_started"
    ACTIVE = "active"
    QUIET = "quiet"
    RESTING = "resting"


def weeks_since(last_prepared_at: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    """Whole weeks between the last prepared activity and `now`, or None if unmeasurable.

    Parses last_prepared_at through parse_timestamptz (the one correct Supabase parser), so an
    odd-microsecond or hours-only-offset timestamp does not silently become None mid-pipeline.
    Returns None when there is no parseable timestamp (no measurement is possible). `now`
    defaults to the current UTC instant; it is a parameter so a test pins exact week boundaries.
    A future last_prepared_at (clock skew) yields 0 weeks, never a negative band.
    """
    parsed = parse_timestamptz(last_prepared_at)
    if parsed is None:
        return None
    reference = now if now is not None else datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta_days = (reference - parsed).days
    if delta_days < 0:
        # last_prepared_at is in the future (clock skew): treat as just-prepared, not negative.
        return 0
    return delta_days // _DAYS_PER_WEEK


def band(
    last_prepared_at: Optional[str],
    activity_count: int,
    now: Optional[datetime] = None,
) -> EngagementBand:
    """Classify one chapter into its engagement band (deterministic, rules-based).

    THE WAS-ACTIVE-THEN-QUIET GUARD FIRST: a chapter with no lifetime prepared activity
    (activity_count <= 0) or no measurable last_prepared_at is NOT_STARTED, never quiet /
    resting. You cannot abandon what you never began, and the dashboard already shows the
    honest grey "Not started" for it. Only a once-active chapter can be quiet / resting.

    Otherwise the band comes from whole weeks since the last prepared activity:
      <= ACTIVE_MAX_WEEKS (4)            -> ACTIVE
      ACTIVE_MAX_WEEKS < w <= QUIET (8)  -> QUIET
      > QUIET_MAX_WEEKS (8)              -> RESTING
    The same inputs always produce the same band (no AI, no randomness).
    """
    # The mandatory guard: zero lifetime activity (or no timestamp to measure from) is the
    # existing NOT_STARTED, never a quiet / resting "you have gone quiet" framing.
    if activity_count <= 0:
        return EngagementBand.NOT_STARTED
    weeks = weeks_since(last_prepared_at, now)
    if weeks is None:
        # A counted activity but no parseable timestamp: cannot measure a gap, so do not
        # invent a quiet / resting band. Fall back to NOT_STARTED's no-extra-signal behaviour.
        return EngagementBand.NOT_STARTED
    if weeks <= ACTIVE_MAX_WEEKS:
        return EngagementBand.ACTIVE
    if weeks <= QUIET_MAX_WEEKS:
        return EngagementBand.QUIET
    return EngagementBand.RESTING
