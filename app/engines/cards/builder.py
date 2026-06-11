"""The Continuity Card assembler (Product.md section 4.6).

A PURE function that turns a stored activity_record (the LCE plan) plus the care
recipient's name into the SAFE one-page card content a HELPER reads. The card
restates the activity's plan in plain, warm, NON-CLINICAL words so a helper (a
babysitter, teacher, or respite carer) who has never met the care recipient can
support them well.

What it assembles (the section 4.6 contents, in order, minus the PDF/QR chrome the
app adds): the care recipient's FIRST name only, the activity name, the
participation tier in plain words, a short supportive intro, the top ~5 strategies
(title + brief detail), and a calm "if things get difficult" line.

THE SAFETY RULES (HardRules/Api/Modules/Cards.md, root CLAUDE.md):
  - FIRST name only. The full name never leaves this module (first_name_only).
  - NO special-category health data and NO clinical language. The card copy is the
    SAME non-clinical surface as the Erosion Alert copy, so it is run through the one
    SHARED guard (app/engines/alerts/guard.py assert_clean). There is no second
    guard: the prohibited-words list and its enforcement live in one place.
  - The copy stays warm, practical, and non-coercive, and signposts nothing medical.

This module holds NO scoring (the tier and strategies come from the stored record;
the engine already ran). It only shapes and guards the helper-facing copy.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.engines.alerts.guard import assert_clean
from app.models.card import CardContent, CardStrategy
from app.models.chapters_v3 import Chapter
from app.models.seed import Tier

# The top N strategies shown on the card. The plan stores its full ranked list; the
# card shows the strongest few so a helper is not overwhelmed (section 4.6: "the full
# strategy list written for an outsider", capped here to the most important ones).
MAX_CARD_STRATEGIES = 5

# The participation tier in plain, warm, helper-facing words. The product tier names
# (Full Engagement / Modified Participation / Continuity Pivot, section 4.4 step 6)
# are restated for someone new: what the tier MEANS for how they support the day, with
# no jargon and no clinical framing. Governed copy in spirit (it is helper-facing and
# safety-sensitive); it is run through the shared non-clinical guard at build time.
_TIER_PLAIN_LABEL: Dict[Tier, str] = {
    Tier.FULL: "Taking part fully",
    Tier.MODIFIED: "Taking part with a few adjustments",
    Tier.PIVOT: "Keeping things calm and steady",
}

# A short supportive intro line per tier: warm, practical, sets the helper's posture
# for the day. Non-clinical, non-coercive (it never instructs a medical action).
_TIER_INTRO: Dict[Tier, str] = {
    Tier.FULL: (
        "Thank you for being here. {name} is usually comfortable with this, so you "
        "can expect a good day. The notes below help you keep it that way."
    ),
    Tier.MODIFIED: (
        "Thank you for being here. {name} can join in well with a little support. "
        "The notes below are what tends to help on the day."
    ),
    Tier.PIVOT: (
        "Thank you for being here. This can be a big ask for {name}, so the goal is "
        "a calm, steady time together rather than getting everything done. The notes "
        "below show what helps most."
    ),
}

# The "if things get difficult" line (section 4.6). Calm, reassuring, non-clinical,
# and NON-coercive: it tells the helper to slow down and reach the family, never to
# take any medical step. The same line for every card, so it is a fixed, guarded
# string.
_IF_DIFFICULT = (
    "If things get difficult, that is okay and it is not your fault. Slow right down, "
    "give {name} space and time, and keep your tone calm. If you are unsure or worried, "
    "contact the family, they would always rather you reached out."
)


def first_name_only(full_name: str) -> str:
    """The first name from a stored name, the ONLY part of the name a card may show.

    Splits on whitespace and returns the first token, so "Ade Bello" becomes "Ade".
    A card carries the care recipient's FIRST name only (the section 4.6 privacy
    rule); the full name never reaches the helper-facing content. An empty or
    whitespace-only name falls back to a neutral, non-identifying word so the copy
    still reads.
    """
    token = (full_name or "").strip().split()
    return token[0] if token else "your child"


def _card_strategies(stored_strategies: Any) -> List[CardStrategy]:
    """The top strategies as helper-facing {title, detail}, capped at MAX_CARD_STRATEGIES.

    Reads the stored activity_record.strategies JSON (an ordered list of
    {title, detail, also_worked_in_chapter}); the order IS the engine's rank (section
    4.4 step 7), so the first few are the strongest. The cross-context label is dropped
    (a helper does not need "also worked in [chapter]"). title falls back to detail (and
    vice versa) so a flat source phrase still yields both fields.
    """
    items = stored_strategies if isinstance(stored_strategies, list) else []
    out: List[CardStrategy] = []
    for raw in items[:MAX_CARD_STRATEGIES]:
        if not isinstance(raw, dict):
            continue
        title = (raw.get("title") or raw.get("detail") or "").strip()
        detail = (raw.get("detail") or raw.get("title") or "").strip()
        if not title and not detail:
            continue
        out.append(CardStrategy(title=title, detail=detail))
    return out


def build_card_content(activity: Dict[str, Any], child_name: str) -> CardContent:
    """Assemble the SAFE Continuity Card content for an activity (section 4.6).

    Pure: given the stored activity_record row (chapter, activity_name, tier,
    strategies) and the care recipient's full name, it shapes the helper-facing
    CardContent, using the FIRST name only. The tier is taken from the stored record
    (the engine already ran; nothing is re-scored here) and expressed in plain words.

    Every emitted string (the intro, the tier label, each strategy title and detail,
    the if-difficult line) is run through the SHARED non-clinical guard
    (app/engines/alerts/guard.py) before the content is returned, so a prohibited
    clinical word, whether in the fixed copy or in a stored strategy, can never leave
    this module onto a shared card. A violation raises ProhibitedWordError (a
    governance error to fix, never silently scrubbed).
    """
    first_name = first_name_only(child_name)
    tier = Tier(activity["tier"])
    chapter = Chapter(activity["chapter"])
    activity_name = activity["activity_name"]

    tier_label = _TIER_PLAIN_LABEL[tier]
    intro = _TIER_INTRO[tier].format(name=first_name)
    if_difficult = _IF_DIFFICULT.format(name=first_name)
    strategies = _card_strategies(activity.get("strategies"))

    # The shared non-clinical guard over EVERY helper-facing string: the same guard the
    # Erosion Alert copy uses (one prohibited-words definition, one enforcement). The
    # activity name and the stored strategy text are user/seed data, so they are guarded
    # too, not just the fixed copy.
    assert_clean(
        activity_name,
        tier_label,
        intro,
        if_difficult,
        *[s.title for s in strategies],
        *[s.detail for s in strategies],
    )

    return CardContent(
        child_first_name=first_name,
        activity_name=activity_name,
        chapter=chapter,
        tier=tier,
        tier_label=tier_label,
        intro=intro,
        strategies=strategies,
        if_difficult=if_difficult,
    )
