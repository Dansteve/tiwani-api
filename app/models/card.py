"""Continuity Card pydantic schemas (v3): the share request + the safe public card.

The cross-repo contract for the Continuity Card endpoints (Product.md section 4.6,
HardRules/Api/Modules/Cards.md). The Continuity Card is a one-page support summary a
Coordinator generates for a HELPER (a babysitter, teacher, or respite carer) and
shares via a link that needs NO account. The app drives the share sheet; a helper
just opens GET /api/v3/cards/{token}.

  - CardStrategy: one strategy on the card, written for an outsider {title, detail}.
  - CardContent: the SAFE public card the token read returns. It carries ONLY the
    care recipient's FIRST name, the activity name, the participation tier (code +
    plain label), a short supportive intro, the top strategies, and an "if things get
    difficult" line. It carries NO user_id / child_id / activity_id and NO clinical
    data: this is the exact shape served without auth, so it must never hold PII
    beyond the first name.
  - CreateCardRequest: the POST /api/v3/cards body {activity_id}.
  - CardCreated: the POST response the owner gets back {content, token, expires_at}.
    The owner needs the token (to build the share link) and the expiry; the helper
    only ever sees CardContent.

The card copy is safety-sensitive and is screened by the shared non-clinical guard
(app/engines/alerts/guard.py) at build time; it must stay warm, practical, and
non-clinical (no medical signposting).
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from app.models.chapters_v3 import Chapter
from app.models.seed import Tier


class CardStrategy(BaseModel):
    """One strategy on the Continuity Card, written for someone new (section 4.6).

    title is the short heading; detail is a brief, plain explanation. Both come from
    the stored activity_record strategies (the seeded, non-clinical strategy text);
    the source carries flat phrases, so title and detail may be the same line.
    """

    model_config = ConfigDict(frozen=True)

    title: str
    detail: str


class CardContent(BaseModel):
    """The SAFE, public Continuity Card content (Product.md section 4.6).

    This is exactly what GET /api/v3/cards/{token} returns to a helper with NO
    account, so it deliberately carries NO PII beyond the care recipient's first name
    and NO clinical data:
      child_first_name  the care recipient's FIRST name only (never the full name).
      activity_name     the activity the helper is supporting.
      chapter           the Life Chapter code (context for the app; not shown raw).
      tier              the participation tier code (Full / Modified / Pivot).
      tier_label        the tier in plain, warm words (what it means for the helper).
      intro             a short supportive intro line.
      strategies        the top strategies, each {title, detail}, for an outsider.
      if_difficult      a calm, non-clinical "if things get difficult" line.
      safety_note       a standing health-and-safety boundary: anything to do with food,
                        medicines, or health follows the family's plan (ask them first),
                        and 999 in an emergency. Deferring, non-clinical, on every card.

    Every string here passes the shared non-clinical guard at build time.
    """

    model_config = ConfigDict(use_enum_values=True)

    child_first_name: str
    activity_name: str
    chapter: Chapter
    tier: Tier
    tier_label: str
    intro: str
    strategies: List[CardStrategy]
    if_difficult: str
    safety_note: str


class CreateCardRequest(BaseModel):
    """The POST /api/v3/cards body: generate a card for one of the caller's activities.

    activity_id is the stored activity_record id (Product.md section 4.4 / 4.6). The
    service verifies the activity belongs to the caller (RLS-scoped) before generating
    the card; an activity the caller does not own is a 404 (we do not confirm it
    exists).
    """

    activity_id: str = Field(..., min_length=1)


class CardCreated(BaseModel):
    """The POST /api/v3/cards response the OWNER receives (section 4.6).

    Carries the safe content (so the app can preview the card), the opaque share
    token (the app builds the share link from it; it is the link's only secret), and
    the expiry (the link is valid 30 days). The helper who opens the link only ever
    sees `content` (CardContent), never the token-bearing owner view.
    """

    content: CardContent
    token: str
    expires_at: datetime
