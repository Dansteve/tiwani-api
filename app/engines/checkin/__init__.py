"""The carer check-in moment ("A moment for you"): GOVERNED, SIGNPOST-ONLY, EPHEMERAL.

The SAFE shape of the carer "a moment for you" entry (ProductReview.md item 9, the
sanctioned "today is hard" door; the psychiatrist board's conditions). It is an OPTIONAL,
occasional acknowledgement of the carer that points to real community/statutory support
and a crisis-capable carer route. It does NOT assess or score the carer (no mood scale, no
"rate your feeling -> tailored response"), it stores NOTHING (ephemeral; not persisted, not
fed to the engine / LCI / alerts, no analytics), and its copy is GOVERNED + guard-tested.

Module file: HardRules/Api/Modules/Checkin.md.

SIGN-OFF GATE: this surface MUST NOT be enabled for real users without psychiatrist + DPO
sign-off (condition 8, Task 12). It is built behind flag.py (OFF by default): the read
route 404s while disabled, so the surface does not exist for users until the sign-off flips
CHECKIN_MOMENT_ENABLED on.

Layout:
  guard.py  the non-clinical + anti-hollow-affirmation guard: PROHIBITED_WORDS (the shared
            clinical set IMPORTED from the alert guard + the hollow-affirmation set) +
            assert_clean, enforced at render time and by the permanent guard test.
  copy.py   GOVERNED COPY: the warm intro, the three COARSE taps (MomentTap), the
            branch acknowledgements, and the community + crisis-capable signposts. Strings
            only; render_moment builds + guards a branch, all_emitted_strings enumerates.
  flag.py   the OFF-by-default sign-off gate (is_checkin_moment_enabled).

The route (app/routes/checkin.py) is a THIN, auth-scoped, READ-ONLY surface that returns
the governed strings and writes nothing; the model (app/models/checkin.py) is the wire
shape. There is NO service / DB layer because there is NOTHING to store.
"""

from app.engines.checkin.copy import (
    MomentContent,
    MomentTap,
    acknowledgement_for,
    all_emitted_strings,
    intro,
    render_moment,
    signposts_for,
    tap_labels,
)
from app.engines.checkin.flag import (
    CHECKIN_MOMENT_FLAG_ENV,
    is_checkin_moment_enabled,
)
from app.engines.checkin.guard import (
    CLINICAL_WORDS,
    HOLLOW_AFFIRMATION_WORDS,
    PROHIBITED_WORDS,
    ProhibitedCopyError,
    assert_clean,
    find_prohibited_words,
)

__all__ = [
    # copy
    "MomentContent",
    "MomentTap",
    "acknowledgement_for",
    "all_emitted_strings",
    "intro",
    "render_moment",
    "signposts_for",
    "tap_labels",
    # flag
    "CHECKIN_MOMENT_FLAG_ENV",
    "is_checkin_moment_enabled",
    # guard
    "CLINICAL_WORDS",
    "HOLLOW_AFFIRMATION_WORDS",
    "PROHIBITED_WORDS",
    "ProhibitedCopyError",
    "assert_clean",
    "find_prohibited_words",
]
