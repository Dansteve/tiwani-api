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

from datetime import datetime, timedelta, timezone

import pytest

import app.routes.cards as cards_routes
import app.services.cards as cards_service
from app.auth import AuthedUser, get_current_user
from app.models.card import (
    CardContent,
    CardCreated,
    CardStatus,
    CardStrategy,
    CardSummary,
)
from tests.fakes_supabase import FakeClient, FakeResponse

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)

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


def _card_row(card_id, *, created_at, expires_at, revoked_at=None, activity_name="School run"):
    """A stored card_record row shaped like the Card History select returns.

    content holds the SAFE first-name-only shape (the list reads activity_name + the
    first name from it); the timestamps are ISO strings, as Supabase returns timestamptz.
    """
    return {
        "id": card_id,
        "child_id": "child-1",
        "activity_id": "act-1",
        "content": {
            "child_first_name": "Ade",
            "activity_name": activity_name,
            "chapter": "school",
        },
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "revoked_at": revoked_at.isoformat() if revoked_at else None,
    }


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
    # The content the owner previews is the safe card shape (now also carrying the
    # freshness note + the read-time staleness signal).
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
        "freshness_note",
        "generated_at",
        "is_stale",
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
    # The function returns no content (the token is unknown, expired, OR revoked) -> None.
    # Migration 0008 adds the `revoked_at is null` clause, so a revoked token reads as
    # missing here exactly like an expired one (both yield no row -> None -> 404).
    fake = FakeClient({("rpc", "get_card_by_token"): FakeResponse(None)})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    assert cards_service.read_card_by_token("expired-or-unknown") is None


# ---------------------------------------------------------------------------
# the freshness / staleness signal on the token read (computed at READ time)
# ---------------------------------------------------------------------------


def test_token_read_backfills_freshness_note_and_marks_an_old_card_stale(monkeypatch):
    # A card stored BEFORE the freshness field existed (no freshness_note in content) but
    # whose merged generated_at is old: the service backfills the governed freshness line
    # and recomputes is_stale True against `now`, without mutating the stored row.
    old_generated = NOW - timedelta(days=45)
    merged = SAFE_CONTENT.model_dump(mode="json")
    merged["freshness_note"] = None
    merged["generated_at"] = old_generated.isoformat()
    merged["is_stale"] = True  # the function already computed it; the service confirms it
    fake = FakeClient({("rpc", "get_card_by_token"): FakeResponse(merged)})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    content = cards_service.read_card_by_token("old-token", now=NOW)
    assert content is not None
    assert content.is_stale is True
    assert content.freshness_note  # backfilled, governed, guarded
    assert "prepared on" in content.freshness_note


def test_token_read_marks_a_fresh_card_not_stale(monkeypatch):
    # A card generated today is not stale; the freshness note baked at create is kept.
    merged = SAFE_CONTENT.model_dump(mode="json")
    merged["generated_at"] = (NOW - timedelta(days=2)).isoformat()
    merged["freshness_note"] = "This plan was prepared on 9 June 2026. ..."
    merged["is_stale"] = False
    fake = FakeClient({("rpc", "get_card_by_token"): FakeResponse(merged)})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    content = cards_service.read_card_by_token("fresh-token", now=NOW)
    assert content is not None
    assert content.is_stale is False
    # The baked freshness note is preserved (not overwritten by the backfill).
    assert content.freshness_note == "This plan was prepared on 9 June 2026. ..."


# ---------------------------------------------------------------------------
# GET /cards (Card History list): requires auth + the CardSummary shape
# ---------------------------------------------------------------------------


def test_list_cards_requires_authentication(client):
    response = client.get("/api/v3/cards")
    assert response.status_code == 401


def test_list_cards_returns_the_cardsummary_shape(authed, monkeypatch):
    summary = CardSummary(
        id="card-1",
        activity_name="School gate drop-off",
        child_first_name="Ade",
        chapter="school",
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        status=CardStatus.ACTIVE,
        generated_at=NOW,
        is_stale=False,
    )
    monkeypatch.setattr(cards_routes.cards_service, "list_cards", lambda user: [summary])
    response = authed.get("/api/v3/cards")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    item = body[0]
    assert set(item.keys()) == {
        "id",
        "activity_name",
        "child_first_name",
        "chapter",
        "created_at",
        "expires_at",
        "status",
        "generated_at",
        "is_stale",
    }
    assert item["status"] == "active"
    # The list is for managing, not re-sharing: it never carries the share token.
    assert "token" not in item


# ---------------------------------------------------------------------------
# SERVICE: list_cards is RLS-scoped, newest-first, and reports the right status
# ---------------------------------------------------------------------------


def test_list_cards_is_user_scoped_and_reports_status_and_staleness(monkeypatch):
    # Three of the caller's cards: one active+fresh, one expired (and old -> stale), one
    # revoked. The service computes status + is_stale at read time from each row.
    rows = [
        _card_row(
            "active-1",
            created_at=NOW - timedelta(days=2),
            expires_at=NOW + timedelta(days=28),
            activity_name="Active card",
        ),
        _card_row(
            "expired-1",
            created_at=NOW - timedelta(days=40),
            expires_at=NOW - timedelta(days=10),
            activity_name="Expired card",
        ),
        _card_row(
            "revoked-1",
            created_at=NOW - timedelta(days=5),
            expires_at=NOW + timedelta(days=25),
            revoked_at=NOW - timedelta(days=1),
            activity_name="Revoked card",
        ),
    ]
    fake = FakeClient({("card_record", "select"): FakeResponse(rows)})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    summaries = cards_service.list_cards(AUTHED, now=NOW)
    by_id = {s.id: s for s in summaries}

    assert by_id["active-1"].status == CardStatus.ACTIVE
    assert by_id["active-1"].is_stale is False
    assert by_id["expired-1"].status == CardStatus.EXPIRED
    assert by_id["expired-1"].is_stale is True  # 40 days old > 30-day window
    assert by_id["revoked-1"].status == CardStatus.REVOKED
    # The read was scoped to the caller (user_id filter) under the caller's token (RLS).
    select_call = next(
        c for c in fake.calls if c["table"] == "card_record" and c["op"] == "select"
    )
    assert ("user_id", "u-1") in select_call["filters"]
    # activity_name + first name come from the stored safe content.
    assert by_id["active-1"].activity_name == "Active card"
    assert by_id["active-1"].child_first_name == "Ade"


def test_list_cards_revoked_takes_precedence_over_expired(monkeypatch):
    # A card that is BOTH revoked and past its expiry reads as REVOKED (the deliberate
    # Coordinator action wins over passive expiry).
    rows = [
        _card_row(
            "rev-exp",
            created_at=NOW - timedelta(days=40),
            expires_at=NOW - timedelta(days=5),
            revoked_at=NOW - timedelta(days=6),
        )
    ]
    fake = FakeClient({("card_record", "select"): FakeResponse(rows)})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    summaries = cards_service.list_cards(AUTHED, now=NOW)
    assert summaries[0].status == CardStatus.REVOKED


# ---------------------------------------------------------------------------
# POST /cards/{card_id}/revoke (soft-revoke): requires auth + the shape + 404
# ---------------------------------------------------------------------------


def test_revoke_card_requires_authentication(client):
    response = client.post("/api/v3/cards/card-1/revoke")
    assert response.status_code == 401


def test_revoke_card_returns_the_revoked_summary(authed, monkeypatch):
    revoked = CardSummary(
        id="card-1",
        activity_name="School gate drop-off",
        child_first_name="Ade",
        chapter="school",
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        status=CardStatus.REVOKED,
        generated_at=NOW,
        is_stale=False,
    )
    monkeypatch.setattr(
        cards_routes.cards_service, "revoke_card", lambda user, card_id: revoked
    )
    response = authed.post("/api/v3/cards/card-1/revoke")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"card"}
    assert body["card"]["status"] == "revoked"
    assert body["card"]["id"] == "card-1"


def test_revoke_card_unknown_card_is_404(authed, monkeypatch):
    def _raise(user, card_id):
        raise cards_service.CardNotFoundError("nope")

    monkeypatch.setattr(cards_routes.cards_service, "revoke_card", _raise)
    response = authed.post("/api/v3/cards/not-mine/revoke")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# SERVICE: revoke_card soft-revokes (sets revoked_at, keeps the row), owner-only
# ---------------------------------------------------------------------------


def test_revoke_card_sets_revoked_at_and_returns_revoked_status(monkeypatch):
    # The owner revokes: the service issues an UPDATE setting revoked_at = now (never a
    # delete), and returns the row as a CardSummary with status REVOKED.
    updated = _card_row(
        "card-1",
        created_at=NOW - timedelta(days=3),
        expires_at=NOW + timedelta(days=27),
        revoked_at=NOW,
    )
    fake = FakeClient({("card_record", "update"): FakeResponse([updated])})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    result = cards_service.revoke_card(AUTHED, "card-1", now=NOW)
    assert result.status == CardStatus.REVOKED
    # It was a soft revoke: an UPDATE setting revoked_at, scoped to the caller's own card.
    update_call = next(
        c for c in fake.calls if c["table"] == "card_record" and c["op"] == "update"
    )
    assert "revoked_at" in update_call["payload"]
    assert ("id", "card-1") in update_call["filters"]
    assert ("user_id", "u-1") in update_call["filters"]
    # No delete was ever issued (soft revoke keeps the audit row).
    assert not any(c.get("op") == "delete" for c in fake.calls)


def test_revoke_card_not_owned_is_card_not_found(monkeypatch):
    # RLS makes another user's card invisible: the update touches no row and the read-back
    # also returns nothing -> CardNotFoundError (the route maps to 404).
    fake = FakeClient(
        {
            ("card_record", "update"): FakeResponse([]),
            ("card_record", "select"): FakeResponse([]),
        }
    )
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)

    with pytest.raises(cards_service.CardNotFoundError):
        cards_service.revoke_card(AUTHED, "not-mine", now=NOW)
