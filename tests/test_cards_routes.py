"""No-DB tests for the v3 Continuity Card endpoints + the cards service (section 4.6).

Two layers, both off a live Supabase (blocked in the sandbox; mocked):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is
    overridden for the authed cases (left real for the 401 case) and the service is
    monkeypatched, so the parse -> call-service -> serialize path and the 401/404/201
    contract are tested. It pins the CardCreated + CardContent shapes the app consumes,
    and that GET /cards/{token} needs NO auth.

  - SERVICE (the real engine + a fake Supabase client): get_anon_client is patched with
    a FakeClient so the REAL section 4.6 assembly runs over scripted rows. This pins
    ownership enforcement (an activity the caller does not own -> 404), the safe content
    the create path returns, and the token read path (valid -> content; expired/invalid
    -> None; and that the content carries NO PII beyond the first name).
"""

from __future__ import annotations

import pytest

import app.routes.cards as cards_routes
import app.services.cards as cards_service
from app.auth import AuthedUser, get_current_user
from app.models.card import CardContent, CardCreated, CardStrategy
from tests.fakes_supabase import FakeClient, FakeResponse

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

SAFE_CONTENT = CardContent(
    child_first_name="Ade",
    activity_name="School gate drop-off",
    chapter="school",
    tier="Pivot",
    tier_label="Keeping things calm and steady",
    intro="Thank you for being here.",
    strategies=[CardStrategy(title="Build in extra time", detail="No rushing at the gate.")],
    if_difficult="If things get difficult, that is okay.",
    safety_note="Follow the family's plan for food, medicines, or Ade's health.",
)


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# POST /cards requires auth; GET /cards/{token} does NOT
# ---------------------------------------------------------------------------


def test_post_cards_requires_authentication(client):
    response = client.post("/api/v3/cards", json={"activity_id": "act-1"})
    assert response.status_code == 401


def test_get_card_by_token_needs_no_auth(client, monkeypatch):
    # No dependency override (no auth): the token read must still work for a helper.
    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_by_token", lambda token: SAFE_CONTENT
    )
    response = client.get("/api/v3/cards/some-token")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /cards route wiring + the CardCreated shape
# ---------------------------------------------------------------------------


def test_post_cards_returns_the_cardcreated_shape(authed, monkeypatch):
    created = CardCreated(
        content=SAFE_CONTENT,
        token="share-tok-123",
        expires_at="2026-07-20T12:00:00+00:00",
    )
    monkeypatch.setattr(
        cards_routes.cards_service,
        "create_card",
        lambda user, *, activity_id: created,
    )
    response = authed.post("/api/v3/cards", json={"activity_id": "act-1"})
    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"content", "token", "expires_at"}
    assert body["token"] == "share-tok-123"
    # The content the owner previews is the safe card shape.
    content = body["content"]
    assert set(content.keys()) == {
        "child_first_name",
        "activity_name",
        "chapter",
        "tier",
        "tier_label",
        "intro",
        "strategies",
        "if_difficult",
        "safety_note",
    }
    assert content["child_first_name"] == "Ade"


def test_post_cards_unknown_activity_is_404(authed, monkeypatch):
    def _raise(user, *, activity_id):
        raise cards_service.CardActivityNotFoundError("nope")

    monkeypatch.setattr(cards_routes.cards_service, "create_card", _raise)
    response = authed.post("/api/v3/cards", json={"activity_id": "not-mine"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /cards/{token} route wiring (valid + 404)
# ---------------------------------------------------------------------------


def test_get_card_by_token_returns_content(client, monkeypatch):
    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_by_token", lambda token: SAFE_CONTENT
    )
    response = client.get("/api/v3/cards/good-token")
    assert response.status_code == 200
    body = response.json()
    assert body["child_first_name"] == "Ade"
    assert body["activity_name"] == "School gate drop-off"
    assert body["tier_label"] == "Keeping things calm and steady"


def test_get_card_by_invalid_or_expired_token_is_404(client, monkeypatch):
    # The service returns None for an unknown OR expired token; the route maps to 404.
    monkeypatch.setattr(cards_routes.cards_service, "read_card_by_token", lambda token: None)
    response = client.get("/api/v3/cards/expired-or-unknown")
    assert response.status_code == 404


def test_get_card_by_token_never_leaks_pii(client, monkeypatch):
    # The wire body is exactly CardContent: no user_id / child_id / activity_id / token.
    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_by_token", lambda token: SAFE_CONTENT
    )
    body = client.get("/api/v3/cards/good-token").json()
    for leaked in ("user_id", "child_id", "activity_id", "token"):
        assert leaked not in body


# ---------------------------------------------------------------------------
# SERVICE: ownership enforced on create
# ---------------------------------------------------------------------------


def test_create_card_enforces_ownership(monkeypatch):
    # The activity_record select returns NO row (RLS makes another user's row
    # invisible) -> CardActivityNotFoundError, which the route maps to 404.
    fake = FakeClient({("activity_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    with pytest.raises(cards_service.CardActivityNotFoundError):
        cards_service.create_card(AUTHED, activity_id="not-mine")


def test_create_card_builds_safe_content_and_stores_it(monkeypatch):
    # The caller owns the activity: the real engine assembles the card, and the service
    # stores a card_record with a token + 30-day expiry, returning the safe content.
    activity = {
        "id": "act-1",
        "user_id": "u-1",
        "child_id": "child-1",
        "chapter": "school",
        "activity_name": "School gate drop-off",
        "tier": "Pivot",
        "strategies": [
            {"title": "Build in extra time", "detail": "No rushing at the gate."},
            {"title": "Do not force", "detail": "Use the agreed alternative."},
        ],
    }
    fake = FakeClient(
        {
            ("activity_record", "select"): FakeResponse([activity]),
            ("child_profile", "select"): FakeResponse([{"id": "child-1", "name": "Ade Bello"}]),
            ("card_record", "insert"): FakeResponse([{"id": "card-1", "token": "x"}]),
        }
    )
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    result = cards_service.create_card(AUTHED, activity_id="act-1")
    assert isinstance(result, CardCreated)
    # First name only (privacy), the plain tier label, and a non-empty token + expiry.
    assert result.content.child_first_name == "Ade"
    assert "Bello" not in result.content.model_dump_json()
    assert result.content.tier_label == "Keeping things calm and steady"
    assert result.token and len(result.token) > 20
    assert result.expires_at is not None
    # The insert carried the token + the safe content jsonb + the 30-day expiry.
    insert_call = next(
        c for c in fake.calls if c.get("op") == "insert" and c["table"] == "card_record"
    )
    payload = insert_call["payload"]
    assert payload["user_id"] == "u-1" and payload["child_id"] == "child-1"
    assert payload["activity_id"] == "act-1"
    assert payload["token"] == result.token
    assert "user_id" not in payload["content"]  # the stored content is the safe shape


# ---------------------------------------------------------------------------
# SERVICE: the token read path (the SECURITY DEFINER function via rpc)
# ---------------------------------------------------------------------------


def test_read_card_by_token_returns_content_for_a_live_token(monkeypatch):
    # The function returns the safe content jsonb; the service validates it to CardContent.
    fake = FakeClient(
        {("rpc", "get_card_by_token"): FakeResponse(SAFE_CONTENT.model_dump(mode="json"))}
    )
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    content = cards_service.read_card_by_token("live-token")
    assert content is not None
    assert content.child_first_name == "Ade"
    # The rpc was called with the token as p_token (the function's only arg).
    rpc_call = next(c for c in fake.calls if "rpc" in c)
    assert rpc_call["rpc"] == "get_card_by_token"
    assert rpc_call["params"] == {"p_token": "live-token"}


def test_read_card_by_token_returns_none_for_an_expired_or_invalid_token(monkeypatch):
    # The function returns no content (the token is unknown or the card expired) -> None.
    fake = FakeClient({("rpc", "get_card_by_token"): FakeResponse(None)})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    assert cards_service.read_card_by_token("expired-or-unknown") is None
