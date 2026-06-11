"""v3 Continuity Card routes (the shareable support summary).

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the cards service
(which verifies ownership, assembles the SAFE content, stores the card, or reads one
by token), serialize. The Continuity Card (Product.md section 4.6) is a one-page
support summary a Coordinator generates for a HELPER and shares via a link that needs
NO account.

Two routes with very different trust:
  POST /api/v3/cards            AUTH REQUIRED. Body {activity_id}. Verifies the
                               activity belongs to the caller, creates the card, and
                               returns the content + share token + expiry. 404 if the
                               activity is not the caller's (we do not confirm it
                               exists). 401 without a valid bearer token.
  GET  /api/v3/cards/{token}    NO AUTH. The helper opens the share link. Returns ONLY
                               the safe content (first name, activity, tier, intro,
                               strategies, if-difficult) if the token is valid and not
                               expired, else 404. Never returns user_id / child_id or
                               any other row: the read goes through the SECURITY
                               DEFINER function (migration 0007), not a table select.

Registered under /api/v3 in main.py. The owner path is user-scoped through the service
with Supabase RLS as the backstop; the token path is the only unauthenticated read and
is deliberately narrow.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthedUser, get_current_user
from app.models.card import CardContent, CardCreated, CreateCardRequest
from app.services import cards as cards_service

router = APIRouter()


@router.post("/cards", response_model=CardCreated, status_code=status.HTTP_201_CREATED)
def create_card(
    payload: CreateCardRequest,
    user: AuthedUser = Depends(get_current_user),
) -> CardCreated:
    """Generate a Continuity Card for one of the caller's activities (section 4.6).

    Verifies the activity_record belongs to the caller (RLS-scoped), assembles the
    SAFE non-clinical content, stores the card_record with a hard-to-guess share token
    and a 30-day expiry, and returns the content + token + expires_at. The app builds
    the share link from the token. 404 if the activity is not the caller's (the row is
    invisible under RLS; we do not confirm it exists). 401 without a valid token.
    """
    try:
        return cards_service.create_card(user, activity_id=payload.activity_id)
    except cards_service.CardActivityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Activity not found",
        ) from exc


@router.get("/cards/{token}", response_model=CardContent)
def read_card(token: str) -> CardContent:
    """Read a shared Continuity Card by its token (NO auth, section 4.6 / 3.3).

    The helper opens the share link; no account is needed. Returns ONLY the safe card
    content (the care recipient's first name, the activity, the tier in plain words, a
    supportive intro, the top strategies, and an "if things get difficult" line) when
    the token is valid and the link has not expired. An unknown or expired token is a
    404 (the app shows a friendly "ask the family for a new one" page). The read never
    exposes user_id / child_id or any other row.
    """
    content = cards_service.read_card_by_token(token)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found or expired",
        )
    return content
