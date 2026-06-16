"""The SIGN-OFF GATE for the per-chapter ENGAGEMENT signal (OFF by default).

The engagement signal (the owner's "disengagement" Tier-1 idea, owner-track Task 12; the
researcher + psychiatrist boards' HONEST shape) is decline-adjacent copy: it tells a carer a
chapter has gone "Quiet" / "Resting". Like the "a moment for you" door, that copy MUST NOT be
enabled for real users without the Task-12 psychiatrist sign-off (root CLAUDE.md launch
gates). This module is that gate: a single flag, OFF by default, that the chapters service
checks. While it is OFF the ChapterStatus.engagement field is omitted (left None), so the
signal does not exist for users; flipping it requires a deliberate environment change that the
sign-off authorises.

The flag is env-driven (ENGAGEMENT_SIGNAL_ENABLED), read at call time (not import time) so a
test can toggle it and an ops change takes effect without a code edit. It defaults to DISABLED:
only an explicit truthy value ("1", "true", "yes", "on", case-insensitive) enables it. Built,
guarded, and tested, but dormant until sign-off.

This is the engagement analogue of app/engines/checkin/flag.py: the decline-adjacent surface
is physically withheld until the sign-off flips the flag on.
"""

from __future__ import annotations

import os

# The env var name. Set it to a truthy value ONLY after the Task-12 psychiatrist sign-off.
ENGAGEMENT_SIGNAL_FLAG_ENV = "ENGAGEMENT_SIGNAL_ENABLED"

# The values that count as "enabled" (case-insensitive). Anything else, including unset, an
# empty string, "0", or "false", leaves the signal OFF.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_engagement_signal_enabled() -> bool:
    """True only when ENGAGEMENT_SIGNAL_ENABLED is an explicit truthy value.

    Read at call time so a test can monkeypatch the environment and an ops toggle takes effect
    without a redeploy of code. Defaults to False (the signal is withheld from the chapters
    feed until the Task-12 psychiatrist sign-off flips it on).
    """
    return os.environ.get(ENGAGEMENT_SIGNAL_FLAG_ENV, "").strip().lower() in _TRUTHY
