"""The SIGN-OFF GATE for the Fusion Layer output (OFF by default).

The Fusion Layer (LCEEngineAddendum.md sections 2 to 6): situated strategies, strategy
provenance grouping, the Specificity Gate, and the value-first enrichment question. Its
situated-strategy templates and enrichment prompts are CARE-ADJACENT GOVERNED COPY that
MUST NOT reach real users without the psychiatrist copy sign-off (FusionBuildIssues.md D2,
root CLAUDE.md launch gates). This module is the SERVER side of that gate, mirroring the
app's NEXT_PUBLIC_FUSION_ENABLED so the copy is gated on BOTH sides until sign-off
(FusionBuildIssues.md G2).

When OFF (the default) the plan response is exactly pre-fusion: the ranked strategy list
is the normal scenario/cross-context list (no situated grouping), and specificity /
enrichment / getting_to_know are omitted; an enrichment_answer is ignored. When ON the full
Fusion output is returned. The engine NUMBERS (the section 4.4 scores, total, tier) are
NEVER affected either way; this only gates what the plan response EXPOSES.

The flag is env-driven (FUSION_ENABLED), read at call time (not import time) so a test can
toggle it and an ops change takes effect without a code edit. It defaults to DISABLED: only
an explicit truthy value ("1", "true", "yes", "on", case-insensitive) enables it. This is
the analogue of app/engines/checkin/flag.py and app/engines/context/flag.py.
"""

from __future__ import annotations

import os

# The env var name. Set it to a truthy value ONLY after the psychiatrist copy sign-off on
# the situated-strategy templates + enrichment questions (the care-adjacent governed copy).
FUSION_FLAG_ENV = "FUSION_ENABLED"

# The values that count as "enabled" (case-insensitive). Anything else, including unset, an
# empty string, "0", or "false", leaves the Fusion output OFF.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_fusion_enabled() -> bool:
    """True only when FUSION_ENABLED is an explicit truthy value.

    Read at call time so a test can monkeypatch the environment and an ops toggle takes
    effect without a code redeploy. Defaults to False (the Fusion output is withheld until
    the psychiatrist copy sign-off flips it on).
    """
    return os.environ.get(FUSION_FLAG_ENV, "").strip().lower() in _TRUTHY
