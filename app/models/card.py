"""Continuity Card pydantic schemas (v3): the share request, the safe public card,
and the Card History list/manage contract.

The cross-repo contract for the Continuity Card endpoints (Product.md section 4.6,
HardRules/Api/Modules/Cards.md). The Continuity Card is a one-page support summary a
Coordinator generates for a HELPER (a babysitter, teacher, or respite carer) and
shares via a link that needs NO account. The app drives the share sheet; a helper
just opens GET /api/v1/cards/{token}.

  - CardStrategy: one strategy on the card, written for an outsider {title, detail}.
  - CardContent: the SAFE public card the token read returns. It carries ONLY the
    care recipient's FIRST name, the activity name, the participation tier (code +
    plain label), a short supportive intro, the top strategies, an "if things get
    difficult" line, a standing safety note, a freshness note, and the read-time
    staleness signal (generated_at + is_stale). It carries NO user_id / child_id /
    activity_id and NO clinical data: this is the exact shape served without auth, so
    it must never hold PII beyond the first name.
  - CreateCardRequest: the POST /api/v1/cards body {activity_id}.
  - CardCreated: the POST response the owner gets back {content, token, expires_at}.
    The owner needs the token (to build the share link) and the expiry; the helper
    only ever sees CardContent.
  - CardStatus / CardSummary: the Card History list. CardSummary is one row of the
    owner's GET /api/v1/cards list: the metadata a Coordinator needs to recognise and
    manage a card (activity, recipient first name, chapter, created/expiry, status,
    and the read-time staleness signal). It is owner-facing (behind auth), still
    first-name-only, and carries no clinical data.
  - CardRevoked: the POST /api/v1/cards/{card_id}/revoke response (the updated row).

The card copy is safety-sensitive and is screened by the shared non-clinical guard
(app/engines/alerts/guard.py) at build time; it must stay warm, practical, and
non-clinical (no medical signposting).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.chapters import Chapter
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

    This is exactly what GET /api/v1/cards/{token} returns to a helper with NO
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
      freshness_note    a governed line naming the date the plan was prepared and asking
                        a helper to request an up-to-date version if the card is old (the
                        clinical board's staleness finding: a card is a point-in-time
                        snapshot). Optional because cards stored before this field existed
                        do not carry it; the read path backfills it from generated_at so
                        every served card still shows the line (the stored row is not
                        mutated). The exact wording is review-deferred to psychiatrist
                        sign-off.
      generated_at      the date/time the card was prepared (its created_at). Surfaced so
                        the app can show the age. A timestamp, not PII.
      is_stale          computed at READ time: True when the card is older than the
                        freshness window (CARD_FRESHNESS_DAYS). Lets the app warn a helper
                        that the strategies may be out of date. Optional/defaulted because
                        the token read merges it in at read time.

    Every governed string here passes the shared non-clinical guard at build time.
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
    freshness_note: Optional[str] = None
    generated_at: Optional[datetime] = None
    is_stale: bool = False


class CreateCardRequest(BaseModel):
    """The POST /api/v1/cards body: generate a card for one of the caller's activities.

    activity_id is the stored activity_record id (Product.md section 4.4 / 4.6). The
    service verifies the activity belongs to the caller (RLS-scoped) before generating
    the card; an activity the caller does not own is a 404 (we do not confirm it
    exists).
    """

    activity_id: str = Field(..., min_length=1)


class CardCreated(BaseModel):
    """The POST /api/v1/cards response the OWNER receives (section 4.6).

    Carries the safe content (so the app can preview the card), the opaque share
    token (the app builds the share link from it; it is the link's only secret), and
    the expiry (the link is valid 30 days). The helper who opens the link only ever
    sees `content` (CardContent), never the token-bearing owner view.
    """

    content: CardContent
    token: str
    expires_at: datetime


class CardStatus(str, Enum):
    """The lifecycle status of a Continuity Card, computed at READ time.

    A card is never stored with a status column; the status is derived from the row on
    each read so it cannot go stale:
      ACTIVE   the link is live (not revoked, not past its expiry).
      EXPIRED  the 30-day link has lapsed (expires_at <= now).
      REVOKED  the Coordinator revoked it (revoked_at is set). A soft revoke: the audit
               row is kept, but the public link is dead.
    Revoked takes precedence over expired (a revoked card reads as revoked even if it
    has also since expired), because revoke is the deliberate Coordinator action.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class CardSummary(BaseModel):
    """One row of the owner's Card History list (GET /api/v1/cards).

    Owner-facing (behind auth, RLS-scoped to the caller), so it carries the metadata a
    Coordinator needs to recognise and manage a card they generated. It is still
    first-name-only and carries NO clinical data and no token (the list is for
    managing, not re-sharing; the token is returned only at create time):
      id             the card_record id (the revoke endpoint takes this).
      activity_name  the activity the card was generated for.
      child_first_name  the care recipient's FIRST name only (from the stored content).
      chapter        the Life Chapter code.
      created_at     when the card was generated.
      expires_at     when the 30-day link lapses.
      status         active / expired / revoked, computed at read time.
      generated_at   alias of created_at, the staleness anchor (mirrors CardContent).
      is_stale       computed at read time: older than the freshness window.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str
    activity_name: str
    child_first_name: str
    chapter: Chapter
    created_at: datetime
    expires_at: datetime
    status: CardStatus
    generated_at: datetime
    is_stale: bool


class CardRevoked(BaseModel):
    """The POST /api/v1/cards/{card_id}/revoke response (the updated card row).

    Returns the card as a CardSummary with status REVOKED and revoked_at set, so the
    app can update the history row in place after the soft revoke. The public link is
    dead the instant this returns (the token read function excludes revoked rows).
    """

    card: CardSummary
