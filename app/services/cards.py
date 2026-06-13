"""Continuity Card data service (v3).

The layer between the card routes and Supabase for the Continuity Card (Product.md
section 4.6, HardRules/Api/Modules/Cards.md). Paths with very different trust:

  - CREATE (auth required): create_card(user, activity_id). Verifies the
    activity_record belongs to the CALLER (RLS-scoped read), reads the care
    recipient's first name, assembles the SAFE card content (app/engines/cards),
    generates a hard-to-guess share token, stores the card_record (content as jsonb,
    expires_at = now + 30 days), confirms the write, and returns the content + token +
    expiry to the owner.

  - LIST (auth required): list_cards(user). The Card History screen: the caller's own
    cards, newest first, each a CardSummary (activity, first name, chapter, created /
    expiry, status, and the read-time staleness signal). RLS-scoped to the caller.

  - REVOKE (auth required, owner only): revoke_card(user, card_id). A SOFT revoke (the
    board's rule: keep the audit row, never hard-delete): sets revoked_at = now() on the
    caller's own card. After it returns, the public token read (the function below)
    excludes the row, so the share link is dead immediately. A card the caller does not
    own is invisible under RLS, so the update touches nothing and is a 404.

  - READ BY TOKEN (NO auth): read_card_by_token(token). The helper has no account, so
    this goes through the SECURITY DEFINER function public.get_card_by_token (migrations
    0007 + 0008), NOT a table select: RLS (keyed to auth.uid()) would return an
    unauthenticated caller nothing. The function returns ONLY the safe content jsonb
    (with the read-time generated_at + is_stale merged in), and ONLY for a token that is
    live (now() < expires_at) AND not revoked, so a token holder can read exactly one
    card's safe copy and no other row or column. A missing / expired / revoked token
    returns None, which the route maps to 404.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every owner path runs
through get_anon_client(user.access_token) so Row Level Security scopes every read and
write to the caller; user_id and child_id are set from the resolved session and the
user's own activity_record, never from the client. The token read path uses an
UNAUTHENTICATED anon client and reaches only the narrow function.

The token is the link's only secret: it is generated with secrets.token_urlsafe (a
cryptographically strong source), so it is not guessable.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.cards import build_card_content, build_freshness_note, public_safe_content
from app.models.card import CardContent, CardCreated, CardStatus, CardSummary
from app.services.profile import _first, _rows
from app.services.timestamps import parse_timestamptz

ACTIVITY_RECORD_TABLE = "activity_record"
CHILD_PROFILE_TABLE = "child_profile"
CARD_RECORD_TABLE = "card_record"
GET_CARD_BY_TOKEN_FN = "get_card_by_token"

# The share link is valid 30 days (section 4.6 / Product.md section 3.3). The card
# stores expires_at = created_at + this; the token read returns the card only while
# now() < expires_at (enforced in SQL by the function, the database backstop).
CARD_VALIDITY_DAYS = 30

# The freshness window for the staleness signal (the clinical board's MANDATORY
# finding: a card is a point-in-time snapshot, so an old card can hand a NEW helper
# outdated strategies). is_stale is True when a card is older than this many days,
# computed at READ time (the stored row is never mutated). It governs the owner's list
# here; the token read function (migration 0008) uses the SAME 30-day interval for the
# public card, so the two agree.
#
# REVIEW-DEFERRED: this threshold AND the freshness-note wording (app/engines/cards/
# builder.py) are the MECHANISM plus reasonable governed copy; the final ratified value
# and wording are deferred to the psychiatrist card-copy sign-off (the board marked them
# deferred).
CARD_FRESHNESS_DAYS = 30

# The number of random bytes behind the share token. token_urlsafe(32) yields a ~43
# char URL-safe string with 256 bits of entropy: not guessable, the link's one secret.
CARD_TOKEN_BYTES = 32


class CardActivityNotFoundError(Exception):
    """Raised when the activity to card does not belong to the caller (route -> 404).

    RLS makes another user's activity_record invisible, so a forged or someone-else's
    activity_id simply reads as missing here; we do not confirm whether the row exists.
    """


class CardNotFoundError(Exception):
    """Raised when the card to revoke does not belong to the caller (route -> 404).

    RLS makes another user's card_record invisible, so a forged or someone-else's
    card_id simply reads as missing here; we do not confirm whether the row exists.
    """


def create_card(
    user: AuthedUser,
    *,
    activity_id: str,
    public_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> CardCreated:
    """Create a Continuity Card for the caller's activity, return content + token + expiry.

    Steps:
      1. read the activity_record by id, RLS-scoped to the caller. Not found (or not
         owned, which RLS renders identical) -> CardActivityNotFoundError (404).
      2. read the caller's care recipient for the FIRST name (the only name on a card).
      3. assemble the SAFE content (app/engines/cards.build_card_content), which runs
         the shared non-clinical guard over every helper-facing string.
      4. generate the share token, store the card_record (content jsonb, expires_at =
         now + 30 days), and CONFIRM the write (read back if no representation).
      5. return the content + token + expiry to the owner.

    now is injectable for tests (the expiry base) and defaults to UTC now; it is the
    only clock this flow uses.
    """
    base_now = now if now is not None else datetime.now(timezone.utc)

    activity = _get_owned_activity(user, activity_id)
    if activity is None:
        raise CardActivityNotFoundError("No activity found to generate a card for")

    child_name = _child_name(user, activity["child_id"])

    # base_now is the card's prepared moment: it anchors the freshness note's date and is
    # carried into the stored content as generated_at, so the prepared date the helper
    # reads matches the card_record.created_at the list reports.
    content = build_card_content(
        activity, child_name, generated_at=base_now, public_name=public_name
    )

    token = secrets.token_urlsafe(CARD_TOKEN_BYTES)
    expires_at = base_now + timedelta(days=CARD_VALIDITY_DAYS)

    _store_card_record(
        user,
        child_id=activity["child_id"],
        activity_id=activity["id"],
        token=token,
        content=content,
        expires_at=expires_at,
    )

    return CardCreated(content=content, token=token, expires_at=expires_at)


def read_card_by_token(token: str, *, now: Optional[datetime] = None) -> Optional[CardContent]:
    """The SAFE card content for a share token, or None if invalid/expired/revoked.

    NO auth. Calls the SECURITY DEFINER function public.get_card_by_token (migrations
    0007 + 0008) through an UNAUTHENTICATED anon client. The function returns ONLY the
    safe content jsonb (with the read-time generated_at + is_stale merged in), and ONLY
    when the token matches a card that is live (expires_at > now()) AND not revoked, so a
    token holder can read exactly that one card's safe copy and nothing else (no user_id
    / child_id / activity_id, no other row). A missing, expired, or revoked token yields
    no content -> None (the route maps to 404).

    Backfill: a card stored before the freshness field existed has no freshness_note in
    its content, so if the function returned a generated_at we compose the governed,
    guarded freshness line here (without mutating the stored row). is_stale is also
    recomputed defensively against `now` (the freshness window) so the owner list and the
    public card never disagree. `now` is injectable for tests; defaults to UTC now.
    """
    client = get_anon_client()
    response = client.rpc(GET_CARD_BY_TOKEN_FN, {"p_token": token}).execute()
    data = getattr(response, "data", None)
    if not data:
        return None
    content = CardContent.model_validate(data)
    # Strip the recipient's NAME for the PUBLIC card: this token read is the ONLY
    # unauthenticated card surface, so the name must not ride on the share link
    # (Docs/FeatureDecisions.md 2026-06-13, the safe-default-first decision). The owner +
    # member-shared card paths do not pass through here, so they keep the first name. Applied
    # on the way out; the stored row is never mutated, so existing and new cards are covered.
    return public_safe_content(_with_freshness(content, now=now))


def read_card_content_by_id(
    user: AuthedUser, card_id: str, *, now: Optional[datetime] = None
) -> Optional[CardContent]:
    """The SAFE content of one of the caller's OWN cards, by card_id (auth, owner only).

    The Card History "View" path: the owner re-opens a card they made. RLS-scoped (the
    select filters by id AND user_id under the caller's token), so a card the caller does
    not own is unreachable and reads as None (the route maps that to 404). Returns the
    stored safe content with the read-time freshness note + is_stale merged in (the same
    shaping the token read uses), so the owner sees exactly the card a helper would,
    including the staleness signal. The share token is NEVER returned (viewing is not
    re-sharing; a fresh share regenerates through create_card). `now` is injectable for
    tests; defaults to UTC now.
    """
    client = get_anon_client(user.access_token)
    row = _first(
        client.table(CARD_RECORD_TABLE)
        .select("content, created_at")
        .eq("id", card_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )
    if row is None:
        return None
    content = CardContent.model_validate(row.get("content") or {})
    if content.generated_at is None:
        created = _parse_dt(row.get("created_at"))
        if created is not None:
            content = content.model_copy(update={"generated_at": created})
    return _with_freshness(content, now=now)


def list_cards(user: AuthedUser, *, now: Optional[datetime] = None) -> List[CardSummary]:
    """The caller's Continuity Cards, newest first, for the Card History screen.

    Reads the caller's own card_record rows (RLS-scoped: the select filters by user_id
    and runs under the caller's token, so another user's cards are physically
    unreachable), newest first, and maps each to a CardSummary. The status (active /
    expired / revoked) and is_stale are computed at READ time from the row against `now`,
    so they cannot go stale and the stored row is never mutated. `now` is injectable for
    tests; defaults to UTC now.
    """
    base_now = now if now is not None else datetime.now(timezone.utc)
    rows = _owned_card_rows(user)
    return [_card_summary(row, now=base_now) for row in rows]


def revoke_card(
    user: AuthedUser, card_id: str, *, now: Optional[datetime] = None
) -> CardSummary:
    """SOFT-revoke one of the caller's cards: set revoked_at = now() (route -> 404 if not owned).

    The board's rule is a SOFT revoke, never a hard delete: the card_record row stays as
    the audit trail and is marked revoked. The update is RLS-scoped (filtered by id AND
    user_id, under the caller's token), so a card the caller does not own is invisible
    and the update touches no row, which we surface as CardNotFoundError (404, not
    confirming the row exists). After this returns, the public token read function
    (migration 0008) excludes the revoked row, so the share link is dead immediately.

    Returns the updated row as a CardSummary (status REVOKED). `now` is injectable for
    tests; defaults to UTC now.
    """
    base_now = now if now is not None else datetime.now(timezone.utc)
    updated = _set_revoked_at(user, card_id, revoked_at=base_now)
    if updated is None:
        raise CardNotFoundError("No card found to revoke")
    return _card_summary(updated, now=base_now)


# ---------------------------------------------------------------------------
# reads / writes (owner path, RLS-scoped)
# ---------------------------------------------------------------------------


def _get_owned_activity(user: AuthedUser, activity_id: str) -> Optional[Dict[str, Any]]:
    """Read the caller's activity_record by id (RLS-scoped); None if not owned.

    The select filters on both id and user_id and runs under the caller's token, so
    RLS plus the explicit user_id filter make another user's row unreachable: a forged
    activity_id matches nothing and returns None (the create path maps that to 404,
    not confirming the row exists).
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("*")
        .eq("id", activity_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )


def _child_name(user: AuthedUser, child_id: str) -> str:
    """The full name of the activity's OWN care recipient (RLS-scoped); "" if absent.

    Reads the specific child_profile the activity_record points to (by child_id,
    scoped to the caller), so the card always names the right recipient (not just the
    most recent one). The builder reduces this to the FIRST name only; "" falls back to
    a neutral word there. RLS makes another user's child invisible, so this can only
    ever read the caller's recipient.
    """
    client = get_anon_client(user.access_token)
    row = _first(
        client.table(CHILD_PROFILE_TABLE)
        .select("name")
        .eq("id", child_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )
    return (row or {}).get("name", "") or ""


def _store_card_record(
    user: AuthedUser,
    *,
    child_id: str,
    activity_id: str,
    token: str,
    content: CardContent,
    expires_at: datetime,
) -> Dict[str, Any]:
    """Insert the card_record and return the stored row (write confirmed).

    user_id is set from the session and child_id/activity_id from the user's own
    activity_record (never from the client); the RLS insert policy additionally
    requires user_id == auth.uid(). content is stored as the SAFE jsonb the token read
    returns. If the insert returns no representation, the row is read back under RLS so
    a card is only ever handed back for a row that exists.
    """
    client = get_anon_client(user.access_token)
    insert_row = {
        "user_id": user.id,
        "child_id": child_id,
        "activity_id": activity_id,
        "token": token,
        "content": content.model_dump(mode="json"),
        "expires_at": expires_at.isoformat(),
    }
    created = _first(client.table(CARD_RECORD_TABLE).insert(insert_row).execute())
    if created is not None:
        return created
    # No representation returned: read back by the unique token under RLS so the write
    # is confirmed before the card is returned.
    confirmed = _first(
        client.table(CARD_RECORD_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .eq("token", token)
        .limit(1)
        .execute()
    )
    if confirmed is None:
        raise RuntimeError("card_record write could not be confirmed")
    return confirmed


def _owned_card_rows(user: AuthedUser) -> List[Dict[str, Any]]:
    """The caller's card_record rows, newest first (RLS-scoped).

    Selects only the columns the Card History list needs (no token, since the list is
    for managing not re-sharing): id, activity name comes from the stored content, plus
    the chapter, the timestamps, and revoked_at for the status. The select filters by
    user_id and runs under the caller's token, so RLS makes another user's cards
    unreachable. Ordered by created_at descending so the screen shows newest first.
    """
    client = get_anon_client(user.access_token)
    return _rows(
        client.table(CARD_RECORD_TABLE)
        .select("id, child_id, activity_id, content, expires_at, created_at, revoked_at")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .execute()
    )


def _set_revoked_at(
    user: AuthedUser, card_id: str, *, revoked_at: datetime
) -> Optional[Dict[str, Any]]:
    """Set revoked_at on the caller's card (RLS-scoped); return the updated row, or None.

    Filters by id AND user_id under the caller's token, so RLS plus the explicit user_id
    filter make another user's card unreachable: the update touches nothing and returns
    no row (the revoke path maps that to 404). The update returns the representation; if
    the driver returns none, the row is read back (still RLS-scoped) so the revoke is
    confirmed before a summary is returned.
    """
    client = get_anon_client(user.access_token)
    updated = _first(
        client.table(CARD_RECORD_TABLE)
        .update({"revoked_at": revoked_at.isoformat()})
        .eq("id", card_id)
        .eq("user_id", user.id)
        .execute()
    )
    if updated is not None:
        return updated
    # No representation: read the row back under RLS to confirm it is the caller's and now
    # revoked. A card the caller does not own reads as None here (a 404 at the route).
    return _first(
        client.table(CARD_RECORD_TABLE)
        .select("id, child_id, activity_id, content, expires_at, created_at, revoked_at")
        .eq("id", card_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )


# ---------------------------------------------------------------------------
# read-time shaping (status + staleness + the freshness backfill)
# ---------------------------------------------------------------------------


def _card_summary(row: Dict[str, Any], *, now: datetime) -> CardSummary:
    """Map a stored card_record row to a CardSummary, computing status + is_stale at read time.

    The status and is_stale are derived from the row against `now`, never stored, so they
    cannot go stale. activity_name and the first name are read from the stored safe
    content (the same first-name-only shape the helper sees); the list never exposes the
    token or any other PII.
    """
    content = row.get("content") or {}
    created_at = _parse_dt(row.get("created_at"))
    expires_at = _parse_dt(row.get("expires_at"))
    revoked_at = _parse_dt(row.get("revoked_at"))
    status = _status_of(expires_at=expires_at, revoked_at=revoked_at, now=now)
    return CardSummary(
        id=row["id"],
        activity_name=content.get("activity_name", ""),
        child_first_name=content.get("child_first_name", ""),
        chapter=content["chapter"],
        created_at=created_at,
        expires_at=expires_at,
        status=status,
        generated_at=created_at,
        is_stale=_is_stale(created_at, now=now),
    )


def _status_of(
    *, expires_at: Optional[datetime], revoked_at: Optional[datetime], now: datetime
) -> CardStatus:
    """The lifecycle status from a row's timestamps (revoked > expired > active).

    Revoked is checked first: a revoked card reads as REVOKED even if it has since also
    expired, because revoke is the deliberate Coordinator action. Otherwise a card whose
    expiry has passed is EXPIRED, and anything still live is ACTIVE.
    """
    if revoked_at is not None:
        return CardStatus.REVOKED
    if expires_at is not None and expires_at <= now:
        return CardStatus.EXPIRED
    return CardStatus.ACTIVE


def _is_stale(generated_at: Optional[datetime], *, now: datetime) -> bool:
    """True when a card is older than the freshness window (CARD_FRESHNESS_DAYS).

    Computed at read time against `now`; the stored row is never mutated, so an old card
    reports stale without being touched. A row with no parseable generated_at is treated
    as not stale (it cannot be aged).
    """
    if generated_at is None:
        return False
    return (now - generated_at) > timedelta(days=CARD_FRESHNESS_DAYS)


def _with_freshness(content: CardContent, *, now: Optional[datetime]) -> CardContent:
    """Backfill the freshness note + recompute is_stale on a token-read CardContent.

    The token read function (migration 0008) merges generated_at + is_stale into the
    safe content. For a card stored BEFORE the freshness field existed, the stored
    content has no freshness_note, so we compose the governed, guarded line here from
    generated_at (without mutating the stored row). is_stale is also recomputed against
    `now` so the public card and the owner list agree. If there is no generated_at, the
    content is returned unchanged.
    """
    if content.generated_at is None:
        return content
    base_now = now if now is not None else datetime.now(timezone.utc)
    note = content.freshness_note or build_freshness_note(content.generated_at)
    return content.model_copy(
        update={
            "freshness_note": note,
            "is_stale": _is_stale(content.generated_at, now=base_now),
        }
    )


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a timestamptz value (ISO string or datetime) to an aware datetime, or None.

    Mirrors the parser in app/services/alerts.py: Supabase returns timestamptz columns as
    ISO strings (sometimes with a trailing Z), which the list/revoke shaping needs as
    aware datetimes to compare against `now`. A naive value is assumed UTC.
    """
    return parse_timestamptz(value)
