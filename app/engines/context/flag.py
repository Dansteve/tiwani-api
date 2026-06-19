"""The SIGN-OFF GATE for the display-only calendar context layer (OFF by default).

The calendar context (FeatureDecisions.md 2026-06-19, the Real-World Context Layer Part B)
is decline-adjacent display copy: it annotates the check-in history with public dates. Like
the engagement signal and the "a moment for you" door, that copy MUST NOT be enabled for
real users without the Task-12 psychiatrist sign-off on the governed copy (root CLAUDE.md
launch gates). This module is that gate: a single flag, OFF by default, that the route
checks. While it is OFF the route returns 404, so the surface does not exist for users;
flipping it requires a deliberate environment change that the sign-off authorises.

The flag is env-driven (CALENDAR_CONTEXT_ENABLED), read at call time (not import time) so a
test can toggle it and an ops change takes effect without a code edit. It defaults to
DISABLED: only an explicit truthy value enables it. This is the analogue of
app/engines/checkin/flag.py and app/engines/engagement/flag.py.
"""

from __future__ import annotations

import os

# The env var name. Set it to a truthy value ONLY after the Task-12 psychiatrist sign-off
# on the governed calendar-context copy.
CALENDAR_CONTEXT_FLAG_ENV = "CALENDAR_CONTEXT_ENABLED"

# The values that count as "enabled" (case-insensitive). Anything else, including unset, an
# empty string, "0", or "false", leaves the surface OFF.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_calendar_context_enabled() -> bool:
    """True only when CALENDAR_CONTEXT_ENABLED is an explicit truthy value.

    Read at call time so a test can monkeypatch the environment and an ops toggle takes
    effect without a code redeploy. Defaults to False (the surface is withheld until the
    Task-12 psychiatrist sign-off flips it on).
    """
    return os.environ.get(CALENDAR_CONTEXT_FLAG_ENV, "").strip().lower() in _TRUTHY
