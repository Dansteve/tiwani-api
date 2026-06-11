"""Continuity Card data service (v3).

The layer between the card routes and Supabase for the Continuity Card (Product.md
section 4.6, HardRules/Api/Modules/Cards.md). Two paths, with very different trust:

  - CREATE (auth required): create_card(user, activity_id). Verifies the
    activity_record belongs to the CALLER (RLS-scoped read), reads the care
    recipient's first name, assembles the SAFE card content (app/engines/cards),
    generates a hard-to-guess share token, stores the card_record (content as jsonb,
    expires_at = now + 30 days), confirms the write, and returns the content + token +
    expiry to the owner.

  - READ BY TOKEN (NO auth): read_card_by_token(token). The helper has no account, so
    this goes through the SECURITY DEFINER function public.get_card_by_token (migration
    0007), NOT a table select: RLS (keyed to auth.uid()) would return an
    unauthenticated caller nothing. The function returns ONLY the safe content jsonb,
    and ONLY for a live (non-expired) token, so a token holder can read exactly one
    card's safe copy and no other row or column. A missing/expired token returns None,
    which the route maps to 404.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): the create path runs
through get_anon_client(user.access_token) so Row Level Security scopes every read and
the insert to the caller; user_id and child_id are set from the resolved session and
the user's own activity_record, never from the client. The token read path uses an
UNAUTHENTICATED anon client and reaches only the narrow function.

The token is the link's only secret: it is generated with secrets.token_urlsafe (a
cryptographically strong source), so it is not guessable.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.cards import build_card_content
from app.models.card import CardContent, CardCreated
from app.services.profile import _first

ACTIVITY_RECORD_TABLE = "activity_record"
CHILD_PROFILE_TABLE = "child_profile"
CARD_RECORD_TABLE = "card_record"
GET_CARD_BY_TOKEN_FN = "get_card_by_token"

# The share link is valid 30 days (section 4.6 / Product.md section 3.3). The card
# stores expires_at = created_at + this; the token read returns the card only while
# now() < expires_at (enforced in SQL by the function, the database backstop).
CARD_VALIDITY_DAYS = 30

# The number of random bytes behind the share token. token_urlsafe(32) yields a ~43
# char URL-safe string with 256 bits of entropy: not guessable, the link's one secret.
CARD_TOKEN_BYTES = 32


class CardActivityNotFoundError(Exception):
    """Raised when the activity to card does not belong to the caller (route -> 404).

    RLS makes another user's activity_record invisible, so a forged or someone-else's
    activity_id simply reads as missing here; we do not confirm whether the row exists.
    """


def create_card(
    user: AuthedUser, *, activity_id: str, now: Optional[datetime] = None
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

    content = build_card_content(activity, child_name)

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


def read_card_by_token(token: str) -> Optional[CardContent]:
    """The SAFE card content for a share token, or None if invalid/expired (NO auth).

    Calls the SECURITY DEFINER function public.get_card_by_token (migration 0007)
    through an UNAUTHENTICATED anon client. The function returns ONLY the content jsonb,
    and ONLY when the token matches a card whose expires_at is still in the future, so
    a token holder can read exactly that one card's safe copy and nothing else (no
    user_id / child_id / activity_id, no other row). A missing or expired token yields
    no content -> None (the route maps to 404).
    """
    client = get_anon_client()
    response = client.rpc(GET_CARD_BY_TOKEN_FN, {"p_token": token}).execute()
    data = getattr(response, "data", None)
    if not data:
        return None
    return CardContent.model_validate(data)


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
