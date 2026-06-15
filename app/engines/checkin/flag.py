"""The SIGN-OFF GATE for the carer check-in moment (OFF by default).

The check-in moment surface (ProductReview.md item 9, the psychiatrist board's SAFE shape)
MUST NOT be enabled for real users without psychiatrist + DPO sign-off (the psychiatrist's
condition 8, root CLAUDE.md launch gates, Task 12). This module is that gate: a single
flag, OFF by default, that the read route checks. While it is OFF the route 404s, so the
surface does not exist for users; flipping it requires a deliberate environment change
that the sign-off authorises.

The flag is env-driven (CHECKIN_MOMENT_ENABLED), read at call time (not import time) so a
test can toggle it and so an ops change takes effect without a code edit. It defaults to
DISABLED: only an explicit truthy value ("1", "true", "yes", "on", case-insensitive)
enables it. Built, guarded, and tested, but dormant until sign-off.

This is the moment's analogue of the alert / village LAUNCH GATE, made enforceable in code:
the alert copy is gated by a process note, this surface is additionally gated by a flag
that physically hides it until enabled.
"""

from __future__ import annotations

import os

# The env var name. Set it to a truthy value ONLY after psychiatrist + DPO sign-off.
CHECKIN_MOMENT_FLAG_ENV = "CHECKIN_MOMENT_ENABLED"

# The values that count as "enabled" (case-insensitive). Anything else, including unset, an
# empty string, "0", or "false", leaves the surface OFF.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_checkin_moment_enabled() -> bool:
    """True only when CHECKIN_MOMENT_ENABLED is an explicit truthy value.

    Read at call time so a test can monkeypatch the environment and an ops toggle takes
    effect without a redeploy of code. Defaults to False (the surface is hidden until
    psychiatrist + DPO sign-off flips it on).
    """
    return os.environ.get(CHECKIN_MOMENT_FLAG_ENV, "").strip().lower() in _TRUTHY
