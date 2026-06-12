"""v1 Continuity Card routes (the shareable support summary + Card History).

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the cards service
(which verifies ownership, assembles the SAFE content, stores / lists / revokes a card,
or reads one by token), serialize. The Continuity Card (Product.md section 4.6) is a
one-page support summary a Coordinator generates for a HELPER and shares via a link that
needs NO account; Card History lets the Coordinator see and manage the cards they made.

The routes, by trust:
  POST   /api/v1/cards                   AUTH REQUIRED. Body {activity_id}. Verifies the
                                         activity belongs to the caller, creates the card,
                                         returns content + share token + expiry. 404 if
                                         the activity is not the caller's. 401 without a
                                         valid bearer token.
  GET    /api/v1/cards                   AUTH REQUIRED. The caller's Card History: their
                                         own cards, newest first, each with status
                                         (active / expired / revoked) and the staleness
                                         signal. RLS-scoped to the caller. 401 without a
                                         valid token.
  POST   /api/v1/cards/{card_id}/revoke  AUTH REQUIRED, owner only. SOFT-revokes the
                                         caller's card (sets revoked_at; the audit row is
                                         kept). 404 if the card is not the caller's. After
                                         it returns, the public token read 404s.
  GET    /api/v1/cards/{card_id}/content AUTH REQUIRED, owner only. The Card History "View":
                                         the owner re-opens their card by id and gets the
                                         SAME safe content a helper sees. 404 if not theirs.
  GET    /api/v1/cards/{card_id}/pdf     AUTH REQUIRED, owner only. The printable export: a
                                         PDF of the SAME governed content as the View (same
                                         read-by-id scoping). 404 if not theirs. A PAID
                                         convenience (the gate wraps this at integration);
                                         the free web card stays browser-printable.
  GET    /api/v1/cards/{token}           NO AUTH. The helper opens the share link. Returns
                                         ONLY the safe content if the token is valid, not
                                         expired, AND not revoked, else 404. Never returns
                                         user_id / child_id or any other row: the read goes
                                         through the SECURITY DEFINER function (migrations
                                         0007 + 0008), not a table select.

Registered under /api/v1 in main.py. The owner paths are user-scoped through the service
with Supabase RLS as the backstop; the token path is the only unauthenticated read and is
deliberately narrow. Note the path order: GET /cards (the list) and the {card_id}/revoke
route are declared before GET /cards/{token}, but FastAPI matches the static and the more
specific paths first regardless, so the token read never shadows them.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import AuthedUser, get_current_user
from app.engines.cards import render_card_pdf
from app.models.card import (
    CardContent,
    CardCreated,
    CardRevoked,
    CardSummary,
    CreateCardRequest,
)
from app.services import cards as cards_service
from app.services.entitlements import EntitlementError, require_entitlement

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


@router.get("/cards", response_model=List[CardSummary])
def list_cards(user: AuthedUser = Depends(get_current_user)) -> List[CardSummary]:
    """List the caller's Continuity Cards, newest first (the Card History screen).

    Returns the caller's own cards (RLS-scoped), each as a CardSummary with the activity,
    the care recipient's first name, the chapter, the created/expiry timestamps, the
    status (active / expired / revoked, computed at read time), and the staleness signal
    (generated_at + is_stale). 401 without a valid token.
    """
    return cards_service.list_cards(user)


@router.post("/cards/{card_id}/revoke", response_model=CardRevoked)
def revoke_card(
    card_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> CardRevoked:
    """Soft-revoke one of the caller's Continuity Cards (owner only, section 4.6).

    Sets revoked_at = now() on the caller's card (the audit row is KEPT, never deleted),
    so the public share link dies immediately (the token read function excludes revoked
    rows). Returns the updated card as a CardSummary with status REVOKED. 404 if the card
    is not the caller's (the row is invisible under RLS; we do not confirm it exists).
    401 without a valid token.
    """
    try:
        card = cards_service.revoke_card(user, card_id)
    except cards_service.CardNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found",
        ) from exc
    return CardRevoked(card=card)


@router.get("/cards/{card_id}/content", response_model=CardContent)
def read_owned_card(
    card_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> CardContent:
    """Read one of the caller's OWN cards in full, by id (AUTH, owner; the View action).

    The Card History "View": the owner re-opens a card they generated, by card_id (NOT the
    share token), so viewing never enables re-sharing a stale link. RLS-scoped: a card the
    caller does not own is a 404 (the row is invisible; we do not confirm it exists).
    Returns the SAFE content (the first name + the plan) with the staleness signal, the
    same shape a helper sees. 401 without a valid token.
    """
    content = cards_service.read_card_content_by_id(user, card_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found",
        )
    return content


@router.get(
    "/cards/{card_id}/pdf",
    responses={200: {"content": {"application/pdf": {}}}},
    response_class=Response,
)
def read_owned_card_pdf(
    card_id: str,
    user: AuthedUser = Depends(get_current_user),
) -> Response:
    """Download one of the caller's OWN cards as a PDF, by id (AUTH, owner; the export).

    The printable Continuity Card: a PDF rendering of the SAME governed content the web
    card shows. It reuses the owner re-open-by-id path (cards_service.read_card_content_by_id):
    RLS-scoped to the caller (select by id AND user_id under the caller's token), so a card
    the caller does not own is unreachable and is a 404 (the row is invisible; we do not
    confirm it exists), exactly like the View endpoint. The resolved CardContent (first
    name only, the supportive intro, the top strategies, the health-and-safety line, the
    if-difficult line, and the freshness note) is laid out by the PURE renderer
    (app/engines/cards.render_card_pdf), which re-runs the SHARED non-clinical guard at
    render time so a prohibited word can never reach the page. The response is an
    application/pdf attachment so the browser downloads it. 401 without a valid token.

    PAID CONVENIENCE (Docs/FeatureDecisions.md): the PDF export is GATED on the
    `card.pdf_export` entitlement, acceptable only because the free public web card is
    browser-printable. The gate is the FIRST line below, BEFORE any card is read or
    rendered: an entitled caller (standard / premium) proceeds; an unentitled caller
    (free) is refused with 402 Payment Required, and the gate FAILS CLOSED, so an
    unknown tier or an unreadable entitlement row also refuses. The free web card stays
    browser-printable, so the safety net is untouched (`card.pdf_export` is a paid
    allowlist key, never a must-stay-free key).
    """
    try:
        require_entitlement(user, "card.pdf_export")
    except EntitlementError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="A paid plan is needed to export this card as a PDF.",
        ) from exc
    content = cards_service.read_card_content_by_id(user, card_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found",
        )
    pdf_bytes = render_card_pdf(content)
    filename = f"continuity-card-{card_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
