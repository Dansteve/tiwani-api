"""GOVERNED COPY for the display-only calendar context layer.

The context layer overlays public calendar dates on the check-in history so a Coordinator
can SEE a quiet stretch fell over (say) the school holidays and judge it for themselves.
Its copy is GOVERNED and decline-adjacent, so every emitted string is WORLD-FACT only: it
states what was true on the calendar, NEVER characterises a dip, a rise, the index, or the
family, and NEVER claims a cause (the panel's conditions, FeatureDecisions.md 2026-06-19).
It is the analogue of app/engines/alerts/copy.py and app/engines/engagement/copy.py.

How the panel's conditions land here:
  - WORLD-FACT, never a verdict on the signal. A note states a date ("Summer holidays
    ... 23 July 2025 to 1 September 2025"), NEVER "this dip is seasonal" / "nothing to
    worry about". The guard (guard.py) bars the editorialising + causal register so a
    future edit cannot drift into it.
  - NON-CAUSAL. No "because" / "due to" / "explained by": the data cannot attribute a
    cause for one family's check-ins. The hedge hands interpretation to the carer.
  - SYMMETRIC by construction. The copy describes a DATE WINDOW; it has no idea whether
    the check-ins around it rose or fell, so it can never soften a decline.
  - The HEDGE makes the firewall visible to the user: these dates are public context
    only, not part of the check-in readings.

Every string here passes the context guard (app/engines/context/guard.py): render
re-checks at emit time and the guard test (tests/test_engine_context_guard.py) pins it
over ALL copy. STRINGS only; the flag that gates the surface lives in flag.py (OFF by
default until sign-off).
"""

from __future__ import annotations

from datetime import date
from typing import List

from app.engines.context.calendar_v1 import ALL_WINDOWS, CalendarWindow
from app.engines.context.guard import assert_clean

# The always-shown neutral header + the honesty hedge. The hedge makes the firewall
# visible: these are public dates, not part of the score, and what they mean is the
# carer's call (the panel's "context you can check", never "context TIWANI accounts for").
CALENDAR_INTRO = (
    "Public dates that fall in this period, shown next to your check-ins so you can "
    "see them for yourself."
)
CALENDAR_HEDGE = (
    "These are public calendar dates only. They are not part of your check-in "
    "readings, and what they mean for your family is for you to decide."
)


def _fmt(day: date) -> str:
    # "26 May 2025": no leading zero on the day, month name in full.
    return f"{day.day} {day.strftime('%B %Y')}"


def render_window_note(window: CalendarWindow) -> str:
    """The GOVERNED world-fact note for one calendar window (guarded at emit time).

    A bank holiday states its label + date; a school-holiday period states its label, its
    approximate England span, and that the dates are approximate. Neither says anything
    about a score, a trajectory, or a cause.
    """
    if window.kind == "bank_holiday":
        note = f"{window.label}, {_fmt(window.start)}."
    else:
        note = (
            f"{window.label} (England state schools, approximate): "
            f"{_fmt(window.start)} to {_fmt(window.end)}."
        )
    assert_clean(note)
    return note


def all_emitted_strings() -> List[str]:
    """Every governed string the calendar context can emit (the guard test iterates this).

    The intro, the hedge, and the note for every window in the reference set. Keeping the
    enumeration here (next to the copy) means a new window or string is covered by the
    guard test automatically.
    """
    strings: List[str] = [CALENDAR_INTRO, CALENDAR_HEDGE]
    strings.extend(render_window_note(window) for window in ALL_WINDOWS)
    return strings
