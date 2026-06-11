"""Erosion Alerts (Product.md section 4.9, AUTHORITATIVE; the copy is GOVERNED).

A governed early-warning signal that a chapter has been under sustained pressure.
Triggered by the COMBINATION of recommended tier and Pulse outcome over time (never
one alone), evaluated after every Pulse, per chapter. A higher level replaces any
lower one.

Module file: HardRules/Api/Modules/Alerts.md. Data object: alert_record
(HardRules/Api/Modules/Models.md, migration 0005).

LAUNCH GATE: the alert COPY does not ship to beta without psychiatrist sign-off
(Task 12 / Product.md section 8 Q6). The engine and the plumbing are built; the copy
that surfaces is governed (app/engines/alerts/copy.py) and must clear sign-off first.

Layout:
  evaluation.py  the PURE, table-driven thresholds: AlertLevel (L1/L2/L3), the
                 ChapterHistory inputs, and evaluate() returning the single highest
                 level met (or None). The only place the section 4.9 numbers live.
  copy.py        GOVERNED COPY: the verbatim L1/L2/L3 prompts + action labels +
                 per-chapter community/statutory signposts. Strings only.
  guard.py       the non-clinical guard: PROHIBITED_WORDS + assert_clean, enforced
                 at render time and by the permanent guard test.

The persistence, the clock, and the post-pulse wiring live in app/services/alerts.py
(it fetches the stored rows, supplies `now`, calls evaluate(), and upserts the
alert_record); this package stays pure.
"""

from app.engines.alerts.copy import (
    AlertCopy,
    Signpost,
    action_label_for,
    all_emitted_strings,
    render_alert,
    render_prompt,
    signposts_for,
)
from app.engines.alerts.evaluation import (
    ActivityPoint,
    AlertLevel,
    ChapterHistory,
    PulseOutcomePoint,
    evaluate,
)
from app.engines.alerts.guard import (
    PROHIBITED_WORDS,
    ProhibitedWordError,
    assert_clean,
    find_prohibited_words,
)

__all__ = [
    # evaluation
    "AlertLevel",
    "ActivityPoint",
    "ChapterHistory",
    "PulseOutcomePoint",
    "evaluate",
    # copy
    "AlertCopy",
    "Signpost",
    "action_label_for",
    "all_emitted_strings",
    "render_alert",
    "render_prompt",
    "signposts_for",
    # guard
    "PROHIBITED_WORDS",
    "ProhibitedWordError",
    "assert_clean",
    "find_prohibited_words",
]
