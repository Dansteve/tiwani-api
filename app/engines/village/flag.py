"""The SIGN-OFF GATE for attaching a Continuity Card to a Village need (OFF by default).

The card-on-task feature (Docs/FeatureDecisions.md 2026-06-17, psychiatrist + DPO BOTH
refine-and-approve) lets a Coordinator attach the recipient's Continuity Card to a delegated
need, visible ONLY to the helper who claims it. It surfaces an already-shareable, PII-stripped,
expiring, revocable card to a TIGHTER audience than the status-quo all-villagers share, but it
is a DIRECTED disclosure of a child's support card to a specific helper, so it MUST NOT be
enabled for real users without the human DPO + psychiatrist sign-off + the sharing DPIA
extension (root CLAUDE.md launch gates). This module is that gate: a single flag, OFF by
default, that the village routes check. While it is OFF an attach request is refused (422) and
no card is ever served on a need (the read route 404s), so the directed disclosure cannot
happen.

The flag is env-driven (CARD_ON_TASK_ENABLED), read at call time (not import time) so a test
can toggle it and an ops change takes effect without a code edit. It defaults to DISABLED:
only an explicit truthy value ("1", "true", "yes", "on", case-insensitive) enables it. Built,
guarded, and tested, but dormant until sign-off.

This is the village analogue of app/engines/checkin/flag.py + app/engines/engagement/flag.py.
"""

from __future__ import annotations

import os

# The env var name. Set it to a truthy value ONLY after the human DPO + psychiatrist sign-off
# + the sharing DPIA extension.
CARD_ON_TASK_FLAG_ENV = "CARD_ON_TASK_ENABLED"

# The values that count as "enabled" (case-insensitive). Anything else, including unset, an
# empty string, "0", or "false", leaves the feature OFF.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_card_on_task_enabled() -> bool:
    """True only when CARD_ON_TASK_ENABLED is an explicit truthy value.

    Read at call time so a test can monkeypatch the environment and an ops toggle takes effect
    without a redeploy of code. Defaults to False (the card attachment is unavailable and no
    card is ever served on a need until the human DPO + psychiatrist sign-off flips it on).
    """
    return os.environ.get(CARD_ON_TASK_FLAG_ENV, "").strip().lower() in _TRUTHY
