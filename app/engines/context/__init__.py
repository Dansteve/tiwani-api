"""The display-only Real-World Context Layer (calendar slice): GOVERNED, flag-OFF.

The smallest safe slice of the Real-World Context Layer (FeatureDecisions.md 2026-06-19,
Part B): public UK calendar dates (bank holidays, exact; school holidays, approximate)
that the app overlays on the check-in history so a Coordinator can tell a seasonal pause
from real narrowing, and judge it for themselves. WORLD-FACTS only, never a verdict on the
signal, never a causal claim, and it touches NO score: the determinism firewall
(tests/test_engine_firewall.py) keeps the LCE/LCI/Alerts unreachable from this module.

Module file: HardRules/Api/Modules/Context.md.

SIGN-OFF GATE: this surface MUST NOT be enabled for real users without the Task-12
psychiatrist sign-off on the governed copy. It is built behind flag.py (OFF by default):
the read route 404s while disabled.

Layout:
  calendar_v1.py  the static public reference set (bank holidays + school-holiday periods),
                  each window carrying its source + a qualitative confidence.
  annotations.py  the PURE builder: resolve + clamp a date range, select overlapping
                  windows (by date only, the symmetry guarantee), render each note.
  copy.py         GOVERNED COPY: the intro, the honesty hedge, and the per-window world-fact
                  notes. STRINGS only; render guards every string at emit time.
  guard.py        the non-clinical + non-editorialising guard (the shared clinical set
                  IMPORTED from the alert guard + the editorialising / causal bans).
  flag.py         the OFF-by-default sign-off gate (is_calendar_context_enabled).

The route (app/routes/context.py) is a THIN, auth-scoped, READ-ONLY surface that reads NO
user data (the calendar is public reference data); the model (app/models/context.py) is the
wire shape. There is NO service / DB layer because there is nothing personal to store.
"""

from app.engines.context.annotations import (
    DEFAULT_LOOKBACK_DAYS,
    MAX_RANGE_DAYS,
    CalendarContext,
    RenderedWindow,
    build_calendar_context,
    resolve_range,
    windows_overlapping,
)
from app.engines.context.calendar_v1 import (
    ALL_WINDOWS,
    COVERAGE_YEARS,
    CalendarWindow,
    all_windows,
)
from app.engines.context.copy import (
    CALENDAR_HEDGE,
    CALENDAR_INTRO,
    all_emitted_strings,
    render_window_note,
)
from app.engines.context.flag import (
    CALENDAR_CONTEXT_FLAG_ENV,
    is_calendar_context_enabled,
)
from app.engines.context.guard import (
    CLINICAL_WORDS,
    EDITORIALISING_WORDS,
    PROHIBITED_WORDS,
    ProhibitedCopyError,
    assert_clean,
    find_prohibited_words,
)

__all__ = [
    # calendar data
    "ALL_WINDOWS",
    "COVERAGE_YEARS",
    "CalendarWindow",
    "all_windows",
    # builder
    "DEFAULT_LOOKBACK_DAYS",
    "MAX_RANGE_DAYS",
    "CalendarContext",
    "RenderedWindow",
    "build_calendar_context",
    "resolve_range",
    "windows_overlapping",
    # copy
    "CALENDAR_HEDGE",
    "CALENDAR_INTRO",
    "all_emitted_strings",
    "render_window_note",
    # flag
    "CALENDAR_CONTEXT_FLAG_ENV",
    "is_calendar_context_enabled",
    # guard
    "CLINICAL_WORDS",
    "EDITORIALISING_WORDS",
    "PROHIBITED_WORDS",
    "ProhibitedCopyError",
    "assert_clean",
    "find_prohibited_words",
]
