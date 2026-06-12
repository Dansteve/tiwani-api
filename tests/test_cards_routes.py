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

import app.engines.cards.pdf as cards_pdf
import app.routes.cards as cards_routes
import app.services.cards as cards_service
from app.auth import AuthedUser, get_current_user
from app.engines.alerts.guard import ProhibitedWordError
from app.engines.cards import render_card_pdf
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
# GET /cards/{card_id}/content (owner View) route + service
# ---------------------------------------------------------------------------


def test_read_owned_card_returns_content(authed, monkeypatch):
    monkeypatch.setattr(
        cards_routes.cards_service,
        "read_card_content_by_id",
        lambda user, card_id: SAFE_CONTENT,
    )
    response = authed.get("/api/v3/cards/card-1/content")
    assert response.status_code == 200
    assert response.json()["child_first_name"] == "Ade"


def test_read_owned_card_not_found_is_404(authed, monkeypatch):
    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_content_by_id", lambda user, card_id: None
    )
    assert authed.get("/api/v3/cards/not-mine/content").status_code == 404


def test_read_owned_card_requires_auth(client):
    # The owner View is auth-gated (401), unlike the public token read.
    assert client.get("/api/v3/cards/card-1/content").status_code == 401


def test_read_card_content_by_id_returns_owned_card(monkeypatch):
    # The caller's own row is returned (RLS-scoped select by id + user_id); the stored
    # content validates to CardContent and the staleness signal is merged in.
    fake = FakeClient(
        {
            ("card_record", "select"): FakeResponse(
                [
                    {
                        "content": SAFE_CONTENT.model_dump(mode="json"),
                        "created_at": "2026-06-11T12:00:00+00:00",
                    }
                ]
            )
        }
    )
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)
    content = cards_service.read_card_content_by_id(AUTHED, "card-1")
    assert content is not None and content.child_first_name == "Ade"


def test_read_card_content_by_id_not_owned_is_none(monkeypatch):
    # RLS makes another user's card invisible -> the select returns no row -> None (404).
    fake = FakeClient({("card_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.cards.get_anon_client", lambda token=None: fake)
    assert cards_service.read_card_content_by_id(AUTHED, "not-mine") is None


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


# ---------------------------------------------------------------------------
# GET /cards/{card_id}/pdf (owner PDF export): auth, owner-only, real PDF out
# ---------------------------------------------------------------------------

# A fully populated governed card for the PDF path: it carries the freshness note and the
# strategy detail, so the renderer assertions can check every block the web card shows.
# (SAFE_CONTENT above is intentionally minimal; we do not mutate it.)
PDF_CONTENT = CardContent(
    child_first_name="Ade",
    activity_name="School gate drop-off",
    chapter="school",
    tier="Pivot",
    tier_label="Keeping things calm and steady",
    intro="Thank you for being here. The notes below show what helps most.",
    strategies=[
        CardStrategy(title="Build in extra time", detail="No rushing at the gate."),
        CardStrategy(title="Offer a calm choice", detail="Two options, never a demand."),
    ],
    if_difficult="If things get difficult, that is okay. Slow right down and contact the family.",
    safety_note=(
        "Follow the family's plan for food, medicines, or Ade's wellbeing; "
        "call 999 in an emergency."
    ),
    freshness_note=(
        "This plan was prepared on 11 June 2026. Ask the family for an up to date "
        "version if it is old."
    ),
    generated_at=NOW,
    is_stale=False,
)


def test_get_card_pdf_requires_authentication(client):
    # The export is auth-gated (401), like the owner View, unlike the public token read.
    assert client.get("/api/v3/cards/card-1/pdf").status_code == 401


def test_get_card_pdf_returns_a_pdf_for_the_owner(authed, monkeypatch):
    # The owner re-open-by-id path resolves the governed content; the route renders it and
    # returns an application/pdf attachment with the real PDF magic bytes. The paid-feature gate
    # is granted here so the test exercises the render path (the 402 deny path is its own test).
    monkeypatch.setattr(cards_routes, "require_entitlement", lambda user, key: None)
    monkeypatch.setattr(
        cards_routes.cards_service,
        "read_card_content_by_id",
        lambda user, card_id: PDF_CONTENT,
    )
    response = authed.get("/api/v3/cards/card-1/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="continuity-card-card-1.pdf"'
    )
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 500  # a non-trivial, rendered document


def test_get_card_pdf_is_402_when_not_entitled(authed, monkeypatch):
    # The paid-feature gate (card.pdf_export) runs FIRST: an unentitled caller (free / unknown
    # tier / unreadable entitlement, the gate fails closed) is refused 402 BEFORE any card is read
    # or rendered. The free web card stays browser-printable, so the safety net is untouched.
    def _deny(user, feature_key):
        assert feature_key == "card.pdf_export"
        raise cards_routes.EntitlementError(feature_key, "free")

    monkeypatch.setattr(cards_routes, "require_entitlement", _deny)

    def _must_not_be_reached(user, card_id):
        raise AssertionError("the card was read before the entitlement gate ran")

    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_content_by_id", _must_not_be_reached
    )
    response = authed.get("/api/v3/cards/card-1/pdf")
    assert response.status_code == 402
    assert response.headers["content-type"] != "application/pdf"


def test_get_card_pdf_not_owned_is_404(authed, monkeypatch):
    # The same scoping as the View: a card the caller does not own resolves to None -> 404,
    # and NO PDF is rendered for it. (The paid-feature gate is granted so we reach the scoping.)
    monkeypatch.setattr(cards_routes, "require_entitlement", lambda user, key: None)
    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_content_by_id", lambda user, card_id: None
    )
    response = authed.get("/api/v3/cards/not-mine/pdf")
    assert response.status_code == 404
    assert response.headers["content-type"] != "application/pdf"


def test_get_card_pdf_uses_the_read_by_id_path_with_the_card_id(authed, monkeypatch):
    # The route passes the path card_id straight to the owner re-open-by-id service call
    # (the same scoping as the View), so the PDF can only ever be of the caller's own card.
    monkeypatch.setattr(cards_routes, "require_entitlement", lambda user, key: None)
    seen = {}

    def _capture(user, card_id):
        seen["user"] = user
        seen["card_id"] = card_id
        return PDF_CONTENT

    monkeypatch.setattr(
        cards_routes.cards_service, "read_card_content_by_id", _capture
    )
    authed.get("/api/v3/cards/card-xyz/pdf")
    assert seen["card_id"] == "card-xyz"
    assert seen["user"].id == "u-1"


# ---------------------------------------------------------------------------
# the PDF renderer: same governed content as the web card + the shared guard
# ---------------------------------------------------------------------------


def _drawn_strings(content: CardContent, monkeypatch) -> str:
    """Render the card and return every string drawn onto the page, joined.

    Captures the text reportlab would put on the page by recording each drawString call
    (the renderer's only text-emitting boundary), so a test can assert the governed copy
    is present without a PDF text-extraction dependency. The renderer wraps long
    paragraphs across several drawString calls, so we join the pieces with spaces and
    collapse whitespace to compare against the source sentences word-for-word.
    """
    captured = []
    real_canvas = cards_pdf.canvas.Canvas

    class RecordingCanvas(real_canvas):
        def drawString(self, x, y, text, *args, **kwargs):
            captured.append(text)
            return super().drawString(x, y, text, *args, **kwargs)

    monkeypatch.setattr(cards_pdf.canvas, "Canvas", RecordingCanvas)
    out = render_card_pdf(content)
    assert out.startswith(b"%PDF")  # a real PDF was still produced
    return " ".join(" ".join(captured).split())


def test_render_card_pdf_draws_the_same_governed_content_as_the_web_card(monkeypatch):
    text = _drawn_strings(PDF_CONTENT, monkeypatch)
    # First name only, never a surname; the activity and the plain tier label.
    assert "Ade" in text
    assert "Bello" not in text  # no full name leaks onto the page
    assert "School gate drop-off" in text
    assert "Keeping things calm and steady" in text
    # The supportive intro, each top strategy (title + detail), and the two standing lines.
    assert "Thank you for being here." in text
    assert "Build in extra time" in text and "No rushing at the gate." in text
    assert "Offer a calm choice" in text and "Two options, never a demand." in text
    assert "call 999 in an emergency" in text  # the health-and-safety line
    assert "If things get difficult, that is okay." in text  # the if-difficult line
    assert "This plan was prepared on 11 June 2026." in text  # the freshness note


def test_render_card_pdf_marks_a_stale_card_with_a_caution(monkeypatch):
    stale = PDF_CONTENT.model_copy(update={"is_stale": True})
    text = _drawn_strings(stale, monkeypatch)
    assert "this card may be out of date" in text  # the stale caution, only when is_stale
    assert "This plan was prepared on 11 June 2026." in text  # the freshness note still shows


def test_render_card_pdf_omits_the_freshness_block_when_absent(monkeypatch):
    # A card with no freshness note (e.g. SAFE_CONTENT, stored before the field) renders
    # without that block, and no stale caution, but is still a valid PDF.
    text = _drawn_strings(SAFE_CONTENT, monkeypatch)
    assert "prepared on" not in text
    assert "this card may be out of date" not in text
    assert "Ade" in text  # the rest of the card still renders


def test_render_card_pdf_enforces_the_shared_non_clinical_guard(monkeypatch):
    # A prohibited clinical word on ANY emitted field must raise at RENDER time (the same
    # one shared guard the assembler uses), so it can never reach a printed page.
    dirty = PDF_CONTENT.model_copy(
        update={"intro": "Thank you for being here. This is not a diagnosis of anything."}
    )
    with pytest.raises(ProhibitedWordError):
        render_card_pdf(dirty)
