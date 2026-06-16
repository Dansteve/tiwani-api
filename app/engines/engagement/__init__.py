"""The per-chapter ENGAGEMENT signal: deterministic band + GOVERNED copy, gated OFF.

The HONEST shape of the owner's "disengagement" Tier-1 idea (owner-track Task 12: "a
previously-active chapter going quiet (no activity for N weeks)"; the researcher +
psychiatrist boards' conditions). Per chapter, it computes a calm band from how long it has
been since the last PREPARED activity (the dashboard's last_prepared_at), and surfaces a
warm, FACTUAL "Quiet" / "Resting" signal on THAT chapter's own card, one chapter at a time
(never a neglected-areas roll-call, which shames). It is deterministic and rules-based (no
AI), the carer is NEVER the subject of a failure sentence, and there is NO count / streak /
trend on the gap.

Module file: HardRules/Api/Modules/CareRecipients.md (the engagement section) +
HardRules/Api/Modules/Dashboard.md.

SIGN-OFF GATE: this decline-adjacent surface MUST NOT be enabled for real users without the
Task-12 psychiatrist sign-off (root CLAUDE.md launch gates). It is built behind flag.py (OFF
by default): while disabled, the chapters service omits the engagement field, so the signal
does not exist for users until the sign-off flips ENGAGEMENT_SIGNAL_ENABLED on (the same
posture as the "a moment for you" door).

Layout:
  bands.py  the deterministic band function: EngagementBand + band() with the PRODUCT-OWNER
            week constants (ACTIVE_MAX_WEEKS / QUIET_MAX_WEEKS) and the mandatory
            was-active-then-quiet guard (zero lifetime activity is NOT_STARTED, never quiet).
  guard.py  the non-clinical + anti-shame / deficit / streak guard: PROHIBITED_WORDS (the
            shared clinical set IMPORTED from the alert guard + the shame / streak set) +
            assert_clean, enforced at render time and by the permanent guard test.
  copy.py   GOVERNED COPY: the band labels ("Quiet" / "Resting" / "No recent plan" /
            "Not started"), the FACTUAL notes about the plan record, and the warm forward
            invitations. Strings only; render_signal builds + guards a band (or None when not
            surfaced), all_emitted_strings enumerates.
  flag.py   the OFF-by-default sign-off gate (is_engagement_signal_enabled).

There is NO route and NO new DB read: the signal rides the EXISTING GET /api/v1/chapters feed
(app/services/chapters.py attaches it to each ChapterStatus when the flag is on), computed from
the activity aggregates the dashboard already reads. The wire shape is the EngagementView on
app/models/chapters.py.
"""

from app.engines.engagement.bands import (
    ACTIVE_MAX_WEEKS,
    QUIET_MAX_WEEKS,
    EngagementBand,
    band,
    weeks_since,
)
from app.engines.engagement.copy import (
    EngagementContent,
    all_emitted_strings,
    label_for,
    render_signal,
)
from app.engines.engagement.flag import (
    ENGAGEMENT_SIGNAL_FLAG_ENV,
    is_engagement_signal_enabled,
)
from app.engines.engagement.guard import (
    CLINICAL_WORDS,
    PROHIBITED_WORDS,
    SHAME_AND_STREAK_WORDS,
    ProhibitedCopyError,
    assert_clean,
    find_prohibited_words,
)

__all__ = [
    # bands
    "ACTIVE_MAX_WEEKS",
    "QUIET_MAX_WEEKS",
    "EngagementBand",
    "band",
    "weeks_since",
    # copy
    "EngagementContent",
    "all_emitted_strings",
    "label_for",
    "render_signal",
    # flag
    "ENGAGEMENT_SIGNAL_FLAG_ENV",
    "is_engagement_signal_enabled",
    # guard
    "CLINICAL_WORDS",
    "PROHIBITED_WORDS",
    "SHAME_AND_STREAK_WORDS",
    "ProhibitedCopyError",
    "assert_clean",
    "find_prohibited_words",
]
