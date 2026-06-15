"""GOVERNED COPY for the carer check-in moment ("A moment for you").

The check-in moment (ProductReview.md item 9, the sanctioned "today is hard" entry; the
psychiatrist board's SAFE shape, the conditions below) is an OPTIONAL, occasional,
SIGNPOST-ONLY acknowledgement of the carer. It is NOT an assessment: it never measures or
scores the carer, there is no mood scale and no "rate your feeling -> tailored response".
The only optional input is a COARSE structured tap ("Doing okay" / "It's a lot" / "Hard
day") whose ONLY effect is to choose which on-screen acknowledgement + signposting block
shows. It stores NOTHING (ephemeral; not persisted, not fed to the engine / LCI / alerts,
no analytics): this module returns strings the app renders in the moment and discards.

Every string here is GOVERNED: WARM, HONEST, NON-clinical, and free of the
hollow-affirmation register. None of it may be paraphrased, reworded, or extended without
the product owner AND the psychiatrist + DPO sign-off that gates this surface (Task 12).
It is the moment's analogue of app/engines/alerts/copy.py. NO app-authored copy, NO LLM
generation: the app renders these governed strings verbatim, exactly as it renders alerts.

How the psychiatrist's conditions land in this copy:
  1. Signposting, not assessment: the moment acknowledges the carer and offers a route to
     the SAME community/statutory support the alerts use (Carers UK, local carer orgs,
     SENDIASS) PLUS a crisis-capable CARER route (Samaritans 116 123, NHS 111, the GP,
     Carers UK). It checks IN on the carer; it never scores them.
  2. Any signal is a COARSE optional tap (MomentTap below), never free text, never a fine
     scale. The tap only branches which block shows.
  5. A "hard day" answer signposts real support calmly and honestly, never advises /
     diagnoses / affirms, and includes the crisis-capable carer route. The tone is the
     section 4.9 L3 register ("you do not have to manage this alone").

Every string in this module passes the check-in guard (app/engines/checkin/guard.py):
render() re-checks at emit time and the guard test pins it over all copy (clinical AND
hollow-affirmation words).

This module holds STRINGS only. The flag that decides WHETHER this surface is enabled for
real users lives in app/engines/checkin/flag.py (OFF by default until sign-off); the read
route is app/routes/checkin.py; both stay separate from the governed words.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from app.engines.alerts.copy import Signpost
from app.engines.checkin.guard import assert_clean


class MomentTap(str, Enum):
    """The COARSE, optional structured tap (the psychiatrist's condition 2).

    Three options, never a fine mood scale and never free text. The tap is OPTIONAL: the
    moment opens with no tap selected (NONE) and shows the always-available support; a tap
    only branches which acknowledgement + signposting block shows. The values are the
    on-the-wire codes the app sends back as ?tap=.
    """

    NONE = "none"
    OKAY = "okay"
    A_LOT = "a_lot"
    HARD = "hard"


@dataclass(frozen=True)
class MomentContent:
    """A rendered check-in moment for one tap branch (the governed content).

    intro is the always-shown warm opener; acknowledgement is the branch-specific honest
    line; signposts are the support resources to show for this branch. This is what
    GET /api/v1/checkin/moment serializes; the app renders it verbatim and authors no
    wording. Nothing here is stored: it is built per request and discarded.
    """

    tap: MomentTap
    intro: str
    acknowledgement: str
    signposts: List[Signpost]


# --- the always-shown warm opener (every branch) ------------------------------
# Acknowledges the carer exists, names that the moment is optional and stores nothing, and
# never asks them to rate themselves. Calm, non-clinical, no affirmation.
_INTRO = (
    "A moment for you. Caring for someone takes a lot, and you matter too. "
    "There is nothing to fill in here and nothing is saved. Whenever you want, "
    "here are people who can help."
)

# --- the COARSE tap labels (the psychiatrist's condition 2) -------------------
# Three options the app shows as taps. NONE has no label (it is the no-tap default state).
_TAP_LABELS: Dict[MomentTap, str] = {
    MomentTap.OKAY: "Doing okay",
    MomentTap.A_LOT: "It's a lot",
    MomentTap.HARD: "Hard day",
}

# --- the branch-specific acknowledgements (governed, honest, never affirming) -
# Each is a calm, honest line, not advice and not a pep talk. The HARD branch uses the
# section 4.9 L3 register ("you do not have to manage this alone") and leads the carer to
# the crisis-capable route below. NONE is the neutral default acknowledgement.
_ACKNOWLEDGEMENTS: Dict[MomentTap, str] = {
    MomentTap.NONE: (
        "However today is going, you do not have to manage it on your own. "
        "These services are here for carers, any time."
    ),
    MomentTap.OKAY: (
        "Glad today feels steady. It can help to know where support is before "
        "you need it, so it is here whenever that changes."
    ),
    MomentTap.A_LOT: (
        "It makes sense that it feels like a lot. You are carrying a great deal, "
        "and you do not have to carry it alone. These services are here for carers."
    ),
    MomentTap.HARD: (
        "A hard day is real, and you do not have to manage this alone. "
        "If things feel like too much right now, you can talk to someone today. "
        "Here are people who will listen and help."
    ),
}


# --- the support signposts ----------------------------------------------------
# COMMUNITY / STATUTORY carer support, shared with the Erosion Alerts (the SAME resources
# the alerts use, ProductReview.md item 9): Carers UK, the local-carer-organisations
# pointer, and SENDIASS for statutory rights. None is a clinical referral.
_CARERS_UK = Signpost("Carers UK", "https://www.carersuk.org")
_LOCAL_CARER_ORGS = Signpost("Local carer support organisations", None)
_SENDIASS = Signpost(
    "SENDIASS (your local SEND advice service)",
    "https://www.kids.org.uk/kids-sendiass/",
)

# The crisis-capable CARER route (the psychiatrist's conditions 1 + 5). These are
# non-clinical, free, listening / general-help routes a carer can reach TODAY: the
# Samaritans (any feeling, any time, free), NHS 111 (the non-emergency front door, urgent
# help and what to do next), the carer's own GP, and Carers UK. This is an HONEST signpost
# for a carer in a hard moment, NOT a clinical-emergency framing and NOT a diagnosis: it
# stays on the wellbeing / signposting side of the line (Psychiatrist.md). The labels carry
# the phone numbers as plain text so the app renders them verbatim (no url for a phone
# route).
_SAMARITANS = Signpost("Samaritans: call 116 123 (free, any time)", "https://www.samaritans.org")
_NHS_111 = Signpost("NHS 111: call 111 for urgent help and advice", "https://111.nhs.uk")
_YOUR_GP = Signpost("Your GP: they can talk through what you need", None)

# The community/statutory set every branch can show.
_COMMUNITY_SIGNPOSTS: List[Signpost] = [_CARERS_UK, _LOCAL_CARER_ORGS, _SENDIASS]

# The crisis-capable set, led for the HARD branch (and offered alongside community support
# on the A_LOT branch). Carers UK closes it so a carer always has the carer-specific body.
_CRISIS_SIGNPOSTS: List[Signpost] = [_SAMARITANS, _NHS_111, _YOUR_GP, _CARERS_UK]

# The signposts shown per branch. The HARD branch leads with the crisis-capable route
# (condition 5); A_LOT shows community support plus the crisis route (the carer who says it
# is a lot still gets the talk-to-someone-today option); OKAY and NONE show the calm
# community set (support before it is needed, no crisis framing pushed on a steady day).
_SIGNPOSTS_BY_TAP: Dict[MomentTap, List[Signpost]] = {
    MomentTap.NONE: _COMMUNITY_SIGNPOSTS,
    MomentTap.OKAY: _COMMUNITY_SIGNPOSTS,
    MomentTap.A_LOT: _COMMUNITY_SIGNPOSTS + [_SAMARITANS, _NHS_111],
    MomentTap.HARD: _CRISIS_SIGNPOSTS,
}


def intro() -> str:
    """The always-shown warm opener (governed, every branch)."""
    return _INTRO


def tap_labels() -> Dict[MomentTap, str]:
    """The three coarse tap labels the app shows (NONE has no label)."""
    return dict(_TAP_LABELS)


def acknowledgement_for(tap: MomentTap) -> str:
    """The branch-specific governed acknowledgement for a tap (honest, never affirming)."""
    return _ACKNOWLEDGEMENTS[tap]


def signposts_for(tap: MomentTap) -> List[Signpost]:
    """The support signposts to show for a tap branch (community + crisis-capable)."""
    return list(_SIGNPOSTS_BY_TAP[tap])


def render_moment(tap: MomentTap = MomentTap.NONE) -> MomentContent:
    """Build the full governed MomentContent for a tap branch, guarded.

    Resolves the always-shown intro, the branch acknowledgement, and the branch signposts,
    then runs the guard over EVERY emitted string (the intro, the acknowledgement, each
    signpost label) so a prohibited clinical OR hollow-affirmation word can never leave the
    engine. Returns the MomentContent the route serializes (and discards after the
    response: nothing is stored).
    """
    intro_text = intro()
    acknowledgement = acknowledgement_for(tap)
    signposts = signposts_for(tap)

    assert_clean(intro_text, acknowledgement, *[s.label for s in signposts])

    return MomentContent(
        tap=tap,
        intro=intro_text,
        acknowledgement=acknowledgement,
        signposts=signposts,
    )


def all_emitted_strings() -> List[str]:
    """Every governed string the moment can emit, across all tap branches.

    The guard test iterates this to assert NO prohibited word (clinical OR
    hollow-affirmation) appears anywhere: the intro, every tap label, each branch
    acknowledgement, and every signpost label. Keeping the enumeration here (next to the
    copy) means a new branch or signpost is covered by the test automatically.
    """
    strings: List[str] = [intro()]
    strings.extend(_TAP_LABELS.values())
    for tap in MomentTap:
        strings.append(acknowledgement_for(tap))
        for signpost in signposts_for(tap):
            strings.append(signpost.label)
    return strings
