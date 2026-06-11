"""GOVERNED COPY, do not change without psychiatrist sign-off (Task 12).

The Erosion Alert copy is AUTHORITATIVE and GOVERNED: every L1/L2/L3 string and
action label below is transcribed VERBATIM from Product.md section 4.9, and the
per-chapter signposts are the community/statutory resources from the Knowledge Base
chapter signpost lists. None of it may be paraphrased, reworded, or extended without
the product owner AND the psychiatrist sign-off that gates the launch (Task 12 /
Product.md section 8 Q6). The only runtime substitution is [chapter] -> the chapter's
display name.

The hard constraint (section 4.9): alerts may only signpost COMMUNITY and STATUTORY
support (Carers UK, IPSEA, SENDIASS, local carer organisations, statutory rights) and
must never use the prohibited clinical words. Every string in this module passes the
non-clinical guard (app/engines/alerts/guard.py); render_alert re-checks at emit time
and the guard test pins it over all copy.

This module holds STRINGS only (the governed text + the resource labels). The
thresholds that decide WHEN a level fires are the engine
(app/engines/alerts/evaluation.py), kept separate so the numeric logic and the
governed words do not entangle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.engines.alerts.evaluation import AlertLevel
from app.engines.alerts.guard import assert_clean
from app.models.chapters_v3 import CHAPTER_DISPLAY_NAMES, Chapter

# The token the governed prompt substitutes with the chapter's display name. It is
# the ONLY substitution section 4.9 allows.
CHAPTER_TOKEN = "[chapter]"


@dataclass(frozen=True)
class Signpost:
    """One community/statutory support resource an alert points to.

    label is the display text the app shows; url is the resource link (None when the
    resource is a local/contextual one without a single canonical link, e.g. "local
    carer support organisations", which the app surfaces as guidance rather than a
    hard link). Both label and any url text are non-clinical (guarded).
    """

    label: str
    url: str | None = None


@dataclass(frozen=True)
class AlertCopy:
    """A rendered alert's governed content for one chapter at one level.

    prompt is the verbatim section 4.9 text with [chapter] resolved to the display
    name; action_label is the verbatim CTA; signposts are the chapter's
    community/statutory resources. This is what GET /api/v3/alerts serializes per
    active alert (the app renders it and never authors its own copy).
    """

    chapter: Chapter
    level: AlertLevel
    prompt: str
    action_label: str
    signposts: List[Signpost]


# --- the verbatim governed prompts (Product.md section 4.9) -------------------
# [chapter] is substituted at render time; everything else is the exact text.
_PROMPT_TEMPLATES: Dict[AlertLevel, str] = {
    AlertLevel.L1: (
        "Your [chapter] chapter has been under some pressure recently. "
        "This is worth paying attention to before it builds. "
        "Would you like to review your support structure?"
    ),
    AlertLevel.L2: (
        "Something to pay attention to. Your [chapter] chapter has been under "
        "sustained pressure for a few weeks. TIWANI noticed. Here are some things "
        "that might help."
    ),
    AlertLevel.L3: (
        "Your [chapter] continuity needs attention. TIWANI has noticed a pattern of "
        "significant disruption. This is exactly what TIWANI is designed to help "
        "with. You do not have to manage this alone."
    ),
}

# --- the verbatim governed action labels (Product.md section 4.9) -------------
_ACTION_LABELS: Dict[AlertLevel, str] = {
    AlertLevel.L1: "Review support options",
    AlertLevel.L2: "See suggestions",
    AlertLevel.L3: "Find support",
}


# --- the per-chapter signposts (community/statutory support only) -------------
# Anchored on the section 4.9 authoritative list (Carers UK, IPSEA, SENDIASS, local
# carer organisations, statutory rights) and specialised per chapter from the
# Knowledge Base chapter signpost lists: the Career chapter adds ACAS workplace
# rights and the flexible-working / Carer's Leave framework; the School chapter
# leads with the SEND statutory bodies IPSEA and SENDIASS. Every chapter includes
# Carers UK and the local-carer-organisations pointer. NONE of these is a clinical
# referral.
_CARERS_UK = Signpost("Carers UK", "https://www.carersuk.org")
_CARERS_UK_WORK = Signpost(
    "Carers UK: work and caring",
    "https://www.carersuk.org/help-and-advice/work-and-career/",
)
_IPSEA = Signpost("IPSEA (SEND legal advice)", "https://www.ipsea.org.uk")
_SENDIASS = Signpost(
    "SENDIASS (your local SEND advice service)",
    "https://www.kids.org.uk/sendiass",
)
_ACAS = Signpost("ACAS: workplace rights", "https://www.acas.org.uk")
_FLEXIBLE_WORKING = Signpost(
    "Flexible working and Carer's Leave (GOV.UK)",
    "https://www.gov.uk/carers-leave",
)
_LOCAL_CARER_ORGS = Signpost("Local carer support organisations", None)

_SIGNPOSTS_BY_CHAPTER: Dict[Chapter, List[Signpost]] = {
    # Career: workplace-rights heavy (KB section 1.5 Level 3 signposts).
    Chapter.CAREER: [_CARERS_UK_WORK, _ACAS, _FLEXIBLE_WORKING, _LOCAL_CARER_ORGS],
    # School: SEND statutory bodies lead (the SEND Code of Practice context).
    Chapter.SCHOOL: [_IPSEA, _SENDIASS, _CARERS_UK, _LOCAL_CARER_ORGS],
    # The remaining chapters use the general carer-support set; the KB lists only
    # "non-clinical community resources" for them, so we point to Carers UK, the
    # local carer organisations, and (for statutory rights) SENDIASS.
    Chapter.FAMILY: [_CARERS_UK, _LOCAL_CARER_ORGS, _SENDIASS],
    Chapter.SOCIAL: [_CARERS_UK, _LOCAL_CARER_ORGS, _SENDIASS],
    Chapter.TRAVEL: [_CARERS_UK, _LOCAL_CARER_ORGS, _SENDIASS],
    Chapter.CULTURE: [_CARERS_UK, _LOCAL_CARER_ORGS, _SENDIASS],
}


def _chapter_enum(chapter: Chapter | str) -> Chapter:
    """Coerce a chapter code or enum to the Chapter enum (the app sends the code)."""
    return chapter if isinstance(chapter, Chapter) else Chapter(chapter)


def render_prompt(chapter: Chapter | str, level: AlertLevel) -> str:
    """The verbatim section 4.9 prompt for a chapter+level, [chapter] resolved.

    Substitutes the chapter's display name (CHAPTER_DISPLAY_NAMES) into the single
    [chapter] token and returns the otherwise-verbatim governed text.
    """
    ch = _chapter_enum(chapter)
    template = _PROMPT_TEMPLATES[level]
    return template.replace(CHAPTER_TOKEN, CHAPTER_DISPLAY_NAMES[ch])


def action_label_for(level: AlertLevel) -> str:
    """The verbatim section 4.9 CTA label for a level."""
    return _ACTION_LABELS[level]


def signposts_for(chapter: Chapter | str) -> List[Signpost]:
    """The community/statutory signposts for a chapter (never a clinical referral)."""
    ch = _chapter_enum(chapter)
    return list(_SIGNPOSTS_BY_CHAPTER[ch])


def render_alert(chapter: Chapter | str, level: AlertLevel) -> AlertCopy:
    """Build the full governed AlertCopy for a chapter at a level, guarded.

    Resolves the verbatim prompt + action label + the chapter's signposts, then runs
    the non-clinical guard over EVERY emitted string (the prompt, the label, each
    signpost label) so a prohibited word can never leave the engine. Returns the
    AlertCopy the route serializes.
    """
    ch = _chapter_enum(chapter)
    prompt = render_prompt(ch, level)
    label = action_label_for(level)
    signposts = signposts_for(ch)

    assert_clean(prompt, label, *[s.label for s in signposts])

    return AlertCopy(
        chapter=ch,
        level=level,
        prompt=prompt,
        action_label=label,
        signposts=signposts,
    )


def all_emitted_strings() -> List[str]:
    """Every governed string the engine can emit, across all chapters and levels.

    The guard test iterates this to assert NO prohibited word appears anywhere: each
    chapter x level prompt, every action label, and every signpost label. Keeping the
    enumeration here (next to the copy) means a new chapter or level is covered by the
    test automatically.
    """
    strings: List[str] = []
    for chapter in Chapter:
        for level in AlertLevel:
            strings.append(render_prompt(chapter, level))
        for signpost in signposts_for(chapter):
            strings.append(signpost.label)
    for level in AlertLevel:
        strings.append(action_label_for(level))
    return strings
