"""The Continuity Card assembler (Product.md section 4.6).

A PURE function that turns a stored activity_record (the LCE plan) plus the care
recipient's name into the SAFE one-page card content a HELPER reads. The card
restates the activity's plan in plain, warm, NON-CLINICAL words so a helper (a
babysitter, teacher, or respite carer) who has never met the care recipient can
support them well.

What it assembles (the section 4.6 contents, in order, minus the PDF/QR chrome the
app adds): the care recipient's FIRST name only, the activity name, the
participation tier in plain words, a short supportive intro, the top ~5 strategies
(title + brief detail), a calm "if things get difficult" line, and a standing
health-and-safety boundary that defers anything medical to the family's own plan.

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

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.engines.alerts.guard import assert_clean
from app.models.card import CardContent, CardStrategy
from app.models.chapters import Chapter
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
# take any medical step. It names the care recipient so a helper never reads the
# difficulty as the child's fault (the psychiatrist re-screen note P1): the fault sits
# with neither party, it is just a hard moment. The same line for every card, so it is
# a fixed, guarded string.
_IF_DIFFICULT = (
    "If things get difficult, that is okay. It is not your fault, and it is not {name}'s "
    "either, this is just a hard moment. Slow right down, give {name} space and time, and "
    "keep your tone calm. If you are unsure or worried, contact the family, they would "
    "always rather you reached out."
)

# A standing health-and-safety boundary shown on EVERY card (the medical re-screen
# finding M1). A helper is not a health professional and the card is not a complete
# instruction set, so for anything touching food, medicines, or the care recipient's
# health the family's own plan governs and the helper asks them first. Non-clinical and
# non-coercive: it defers, it never instructs a medical step, and it signposts only the
# family and, for a genuine emergency, the universal emergency number. Fixed copy, run
# through the shared guard like every other line.
_SAFETY_NOTE = (
    "For anything to do with food, allergies, medicines, or {name}'s health, follow the "
    "family's instructions and ask them first. If you are ever worried about {name}'s "
    "wellbeing, contact the family straight away, and call 999 in an emergency."
)

# The freshness note shown on EVERY card (the clinical board's MANDATORY staleness
# finding). A card is a point-in-time SNAPSHOT: the care recipient's needs, profile, and
# the strategies that help all change over time, so an old card can hand a NEW helper
# advice that no longer fits. This line names the date the plan was prepared and asks a
# helper to request an up-to-date version if the card is more than a few weeks old. Calm,
# non-clinical, non-coercive (it defers to the family, it instructs no medical step), and
# run through the shared guard like every other line. {date} is the prepared date.
#
# REVIEW-DEFERRED: this exact wording AND the freshness threshold (CARD_FRESHNESS_DAYS in
# app/services/cards.py, the is_stale window) are the MECHANISM plus reasonable governed
# copy; the final ratified wording and threshold are deferred to the psychiatrist
# card-copy sign-off (the board marked them deferred).
_FRESHNESS_NOTE = (
    "This plan was prepared on {date}. A child's needs change over time, so if this is "
    "more than a few weeks old, please ask the family for an up to date version."
)


def _format_prepared_date(when: datetime) -> str:
    """A readable prepared-date for the freshness note, e.g. "5 June 2026".

    No leading zero on the day and no em or en dashes (writing conventions). Used only
    for the human-facing freshness sentence; the machine-readable generated_at carries
    the full timestamp.
    """
    return f"{when.day} {when.strftime('%B %Y')}"


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


def build_freshness_note(generated_at: datetime) -> str:
    """The governed, guarded freshness line for a card prepared at generated_at.

    Names the prepared date in plain words and asks for an up-to-date version if the
    card is old (the staleness finding). Run through the SHARED non-clinical guard
    before it is returned, like every other card string. Exposed separately so the
    read path can backfill the line for a card stored before this field existed,
    without re-assembling the whole card or mutating the stored row.
    """
    note = _FRESHNESS_NOTE.format(date=_format_prepared_date(generated_at))
    assert_clean(note)
    return note


def build_card_content(
    activity: Dict[str, Any],
    child_name: str,
    *,
    generated_at: Optional[datetime] = None,
    public_name: Optional[str] = None,
) -> CardContent:
    """Assemble the SAFE Continuity Card content for an activity (section 4.6).

    Pure: given the stored activity_record row (chapter, activity_name, tier,
    strategies) and the care recipient's full name, it shapes the helper-facing
    CardContent, using the FIRST name only. The tier is taken from the stored record
    (the engine already ran; nothing is re-scored here) and expressed in plain words.

    generated_at is the moment the card is being prepared (the card_record.created_at).
    It anchors the freshness note (the prepared date) and is carried back as
    CardContent.generated_at so the app can show the card's age. is_stale is NOT set
    here (it is a read-time computation against the freshness window, done by the
    service / the token read function): a freshly built card is, by definition, not
    stale, so it stays at the model default False.

    Every governed string (the intro, the tier label, each strategy title and detail,
    the if-difficult line, the safety note, the freshness note) is run through the
    SHARED non-clinical guard (app/engines/alerts/guard.py) before the content is
    returned, so a prohibited clinical word, whether in the fixed copy or in a stored
    strategy, can never leave this module onto a shared card. A violation raises
    ProhibitedWordError (a governance error to fix, never silently scrubbed).
    """
    first_name = first_name_only(child_name)
    tier = Tier(activity["tier"])
    chapter = Chapter(activity["chapter"])
    activity_name = activity["activity_name"]
    prepared_at = generated_at if generated_at is not None else datetime.now(timezone.utc)

    tier_label = _TIER_PLAIN_LABEL[tier]
    intro = _TIER_INTRO[tier].format(name=first_name)
    if_difficult = _IF_DIFFICULT.format(name=first_name)
    safety_note = _SAFETY_NOTE.format(name=first_name)
    freshness_note = _FRESHNESS_NOTE.format(date=_format_prepared_date(prepared_at))
    strategies = _card_strategies(activity.get("strategies"))
    # The owner-chosen PUBLIC-card label (an initial / nickname / first name), or None for no
    # name; trimmed here, capped at the request layer, guarded below like every other string.
    public_label = (public_name or "").strip() or None

    # The shared non-clinical guard over EVERY helper-facing string: the same guard the
    # Erosion Alert copy uses (one prohibited-words definition, one enforcement). The
    # activity name and the stored strategy text are user/seed data, so they are guarded
    # too, not just the fixed copy; the owner's public_label is user text on a public card,
    # so it is guarded too.
    assert_clean(
        activity_name,
        tier_label,
        intro,
        if_difficult,
        safety_note,
        freshness_note,
        *[s.title for s in strategies],
        *[s.detail for s in strategies],
        *([public_label] if public_label else []),
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
        safety_note=safety_note,
        freshness_note=freshness_note,
        generated_at=prepared_at,
        public_label=public_label,
    )


# ---------------------------------------------------------------------------
# the PUBLIC (unauthenticated) card: the same content with the recipient's NAME removed
# ---------------------------------------------------------------------------

# The token-link card (GET /api/v1/cards/{token}) is resolvable with NO account, so it must
# NOT carry the care recipient's name: a child's name beside their support needs on an
# unauthenticated bearer link is sensitive data exposed without auth (Docs/FeatureDecisions.md
# 2026-06-13, the "safe default first" decision; the lawyer/DPO pre-screen). The name is baked
# into exactly four fields at build time (child_first_name, intro, if_difficult, safety_note);
# every other field (activity, tier label, strategies, freshness note) carries no name. The
# name-FREE variants below mirror the name-bearing copy above, with the first name replaced by a
# neutral pronoun ("they"/"them"/"their") so a helper still reads warm, complete guidance, just
# never the name; the heading stands in a neutral label. (De-childing these for adult recipients,
# D8, is the SAME tracked follow-up as the name-bearing copy.) Member-shared + owner card paths do
# NOT use these (an access-controlled surface keeps the first name); only the public read does.

# The heading label that stands in for the name on the public card ("Supporting: this child").
_PUBLIC_RECIPIENT_LABEL = "this child"

_PUBLIC_TIER_INTRO: Dict[Tier, str] = {
    Tier.FULL: (
        "Thank you for being here. They are usually comfortable with this, so you "
        "can expect a good day. The notes below help you keep it that way."
    ),
    Tier.MODIFIED: (
        "Thank you for being here. They can join in well with a little support. "
        "The notes below are what tends to help on the day."
    ),
    Tier.PIVOT: (
        "Thank you for being here. This can be a big ask for them, so the goal is "
        "a calm, steady time together rather than getting everything done. The notes "
        "below show what helps most."
    ),
}

_PUBLIC_IF_DIFFICULT = (
    "If things get difficult, that is okay. It is not your fault, and it is not theirs "
    "either, this is just a hard moment. Slow right down, give them space and time, and "
    "keep your tone calm. If you are unsure or worried, contact the family, they would "
    "always rather you reached out."
)

_PUBLIC_SAFETY_NOTE = (
    "For anything to do with food, allergies, medicines, or their health, follow the "
    "family's instructions and ask them first. If you are ever worried about their "
    "wellbeing, contact the family straight away, and call 999 in an emergency."
)


def public_safe_content(content: CardContent) -> CardContent:
    """Return the card content with the care recipient's NAME removed, for the PUBLIC card.

    GET /api/v1/cards/{token} is resolvable with no account, so the name must not ride on it
    (Docs/FeatureDecisions.md 2026-06-13). The name is baked into four fields at build time
    (child_first_name, intro, if_difficult, safety_note); this swaps those four for the
    name-free variants (the owner's chosen public label if any, else a neutral heading, + the
    pronoun copy of the SAME tier), leaving
    every other field untouched (activity, chapter, tier, tier_label, strategies,
    freshness_note, generated_at, is_stale). Pure: the stored row is never mutated (the read
    path applies this on the way out, so existing AND new cards are covered). The member-shared
    and owner card paths do NOT call this, so they keep the first name (an access-controlled
    surface). The neutral copy is fixed governed copy, screened against the prohibited-words
    guard by a test (in CI, never at request time).
    """
    intro = _PUBLIC_TIER_INTRO[Tier(content.tier)]
    # The heading is the owner's chosen public label if they opted in at create
    # (an initial / nickname / first name), otherwise the neutral "this child" (no name).
    return content.model_copy(
        update={
            "child_first_name": content.public_label or _PUBLIC_RECIPIENT_LABEL,
            "intro": intro,
            "if_difficult": _PUBLIC_IF_DIFFICULT,
            "safety_note": _PUBLIC_SAFETY_NOTE,
        }
    )
