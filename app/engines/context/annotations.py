"""The PURE calendar-context builder for the display-only context layer.

Given a date range, return the public calendar windows that overlap it, each rendered with
its GOVERNED world-fact note. Pure and deterministic: no DB, no wall clock (the `today`
used for defaulting is PASSED IN by the caller, never read here), and NO score input at
all.

SYMMETRY by construction (the panel's anti-masking condition): this builder selects
windows by DATE ONLY. It cannot see a score, a trajectory, a dip, or a rise, so it
annotates a good stretch exactly as it annotates a quiet one. There is no code path that
softens a decline, because no decline is in scope here. The check-in numbers (section 4.8)
are produced elsewhere and are byte-identical whether or not this builder ever runs; the
determinism firewall (tests/test_engine_firewall.py) keeps this module unreachable from
the LCE/LCI/Alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

from app.engines.context.calendar_v1 import CalendarWindow, all_windows
from app.engines.context.copy import CALENDAR_HEDGE, CALENDAR_INTRO, render_window_note

# The widest range the builder will honour, so a caller cannot ask for an unbounded sweep
# of the reference set (the every-list-is-capped posture). About two years, enough to
# cover a check-in history plus headroom.
MAX_RANGE_DAYS = 800

# The default look-back when a caller gives no explicit `from` (an ~18-month window up to
# `today`), so the endpoint has a sensible bounded default.
DEFAULT_LOOKBACK_DAYS = 550


@dataclass(frozen=True)
class RenderedWindow:
    """A calendar window paired with its governed, guarded world-fact note."""

    window: CalendarWindow
    note: str


@dataclass(frozen=True)
class CalendarContext:
    """The full display-only calendar context for a date range (what the route serializes).

    The resolved [from_date, to_date] span, the governed intro + hedge, and the overlapping
    windows in date order, each with its note. Carries NO score and NO trajectory: it is
    reference context the app overlays on the check-in history it already has.
    """

    from_date: date
    to_date: date
    intro: str
    hedge: str
    windows: List[RenderedWindow]


def windows_overlapping(
    windows: List[CalendarWindow], range_start: date, range_end: date
) -> List[CalendarWindow]:
    """The windows whose [start, end] intersects [range_start, range_end], by start date.

    Inclusive on both ends. Blind to anything but the dates (the symmetry guarantee).
    """
    hits = [w for w in windows if w.start <= range_end and w.end >= range_start]
    return sorted(hits, key=lambda w: (w.start, w.end, w.label))


def resolve_range(
    today: date, from_: Optional[date], to: Optional[date]
) -> Tuple[date, date]:
    """Resolve + clamp the [from, to] range from optional inputs and an injected `today`.

    Defaults: `to` is `today`, `from` is DEFAULT_LOOKBACK_DAYS before `to`. A reversed range
    is normalised, then the span is clamped to MAX_RANGE_DAYS (the `from` edge pulled
    forward), so the read is always bounded and well-formed.
    """
    end = to or today
    start = from_ or (end - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    if start > end:
        start, end = end, start
    if (end - start).days > MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS)
    return start, end


def build_calendar_context(
    today: date, from_: Optional[date] = None, to: Optional[date] = None
) -> CalendarContext:
    """Build the governed calendar context for the resolved range (pure, deterministic).

    Resolves + clamps the range, selects the overlapping windows (by date only), renders
    each note through the guarded governed copy, and returns the assembled context. Same
    inputs always produce the same output.
    """
    start, end = resolve_range(today, from_, to)
    hits = windows_overlapping(all_windows(), start, end)
    rendered = [RenderedWindow(window=w, note=render_window_note(w)) for w in hits]
    return CalendarContext(
        from_date=start,
        to_date=end,
        intro=CALENDAR_INTRO,
        hedge=CALENDAR_HEDGE,
        windows=rendered,
    )
