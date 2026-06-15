"""No-DB tests for the v3 Shared-Child sharing endpoints + the sharing service.

Two layers, both off a live Supabase (blocked in the sandbox; mocked):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is overridden
    for the authed cases (left real for the 401 case) and the service is monkeypatched, so
    the parse -> call-service -> serialize path and the 401/404/409/400/201 contract are
    tested. It pins the InviteCreated / Roster / SharedCard shapes the app consumes and the
    copy_key contract (the api returns governed copy keys, never the role names as labels).

  - SERVICE (the real service + a fake Supabase client): get_anon_client is patched with a
    FakeClient so the REAL service logic runs over scripted rows / RPC results. This pins
    the ownership gate (a recipient the caller does not own -> RecipientNotOwnedError), the
    consent-recorded invite, the ADULT block (an adult share with no recorded consent ->
    AdultConsentRequiredError), the redeem path, the roster (members + pending invites), the
    instant revoke, and the CAPPED card read (the visibility ceiling, via
    get_recipient_card_for_member).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.services.sharing as sharing_service
from app.auth import AuthedUser, get_current_user
from app.engines.sharing import copy as sharing_copy
from app.models.sharing import (
    ConsentRecorded,
    InviteCreated,
    RedeemResult,
    RevokeResult,
    Roster,
    RosterEntry,
    RosterStatus,
    SharedCard,
    SharedRecipient,
    SharedWithMe,
    ShareRole,
    SubjectKind,
)
from tests.fakes_supabase import FakeClient, FakeResponse

AUTHED = AuthedUser(id="owner-1", email="ada@example.com", access_token="tok-abc")
VIEWER = AuthedUser(id="viewer-1", email="ben@example.com", access_token="tok-xyz")

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(days=7)

OWNED_CHILD = {"id": "recip-1", "user_id": "owner-1", "name": "Ade Bello"}

# The SAFE card content shape get_recipient_card_for_member returns (first name only).
SAFE_CARD_JSON = {
    "child_first_name": "Ade",
    "activity_name": "School gate drop-off",
    "chapter": "school",
    "tier": "Pivot",
    "tier_label": "Keeping things calm and steady",
    "intro": "Thank you for being here.",
    "strategies": [{"title": "Build in extra time", "detail": "No rushing at the gate."}],
    "if_difficult": "If things get difficult, that is okay.",
    "safety_note": "Follow the family's plan for food, medicines, or Ade's health.",
    "generated_at": NOW.isoformat(),
    "is_stale": False,
}


def _patch_client(monkeypatch, fake: FakeClient) -> None:
    """Point get_anon_client at the fake in BOTH modules the sharing service reads through.

    The sharing service does its own reads (recipient_membership / recipient_invite + the
    RPCs) via app.services.sharing.get_anon_client, but it delegates the OWNER ownership
    check to app.services.profile (resolve_child_id / get_child_by_id), which uses the
    profile module's own get_anon_client. Patch both so no read escapes to a real Supabase.
    """
    import app.services.profile as profile_service

    monkeypatch.setattr(sharing_service, "get_anon_client", lambda *a, **k: fake)
    monkeypatch.setattr(profile_service, "get_anon_client", lambda *a, **k: fake)


# ===========================================================================
# ROUTE wiring (TestClient): auth, status codes, the copy_key contract.
# ===========================================================================


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


def test_invite_requires_auth(client):
    # No dependency override: the real current-user dep runs and rejects (no token -> 401).
    resp = client.post(
        "/api/v1/sharing/invites",
        json={"recipient_id": "recip-1", "email": "ben@example.com"},
    )
    assert resp.status_code == 401


def test_invite_happy_path_returns_token_and_governed_copy(authed, monkeypatch):
    created = InviteCreated(
        invite_id="inv-1",
        token="tok-share",
        join_code="KJBJQ-DVF61",
        join_code_copy_key=sharing_copy.JOIN_CODE_COPY_KEY,
        role=ShareRole.VIEWER,
        expires_at=EXPIRES,
        copy_key=sharing_copy.INVITE_COPY_KEY,
        consent_text="I confirm I have the authority to share Ade's support information ...",
    )
    monkeypatch.setattr(sharing_service, "invite_viewer", lambda *a, **k: created)

    resp = authed.post(
        "/api/v1/sharing/invites",
        json={"recipient_id": "recip-1", "email": "ben@example.com"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token"] == "tok-share"
    assert body["invite_id"] == "inv-1"
    assert body["role"] == "viewer"
    # The copy_key contract: a governed key, never a role label printed as copy.
    assert body["copy_key"] == sharing_copy.INVITE_COPY_KEY
    assert "consent_text" in body
    # The short typable join code is returned (display form) with its governed copy key.
    assert body["join_code"] == "KJBJQ-DVF61"
    assert body["join_code_copy_key"] == sharing_copy.JOIN_CODE_COPY_KEY


def test_invite_unowned_recipient_is_404(authed, monkeypatch):
    def _raise(*a, **k):
        raise sharing_service.RecipientNotOwnedError("nope")

    monkeypatch.setattr(sharing_service, "invite_viewer", _raise)
    resp = authed.post(
        "/api/v1/sharing/invites",
        json={"recipient_id": "not-mine", "email": "ben@example.com"},
    )
    assert resp.status_code == 404


def test_invite_adult_without_consent_is_409(authed, monkeypatch):
    def _raise(*a, **k):
        raise sharing_service.AdultConsentRequiredError("needs consent")

    monkeypatch.setattr(sharing_service, "invite_viewer", _raise)
    resp = authed.post(
        "/api/v1/sharing/invites",
        json={
            "recipient_id": "recip-1",
            "email": "ben@example.com",
            "subject_kind": "adult",
        },
    )
    # The MVP adult block surfaces as a calm 409 (not a 4xx the user "did wrong").
    assert resp.status_code == 409


def test_redeem_bad_token_is_400(authed, monkeypatch):
    def _raise(*a, **k):
        raise sharing_service.InviteRedeemError("expired")

    monkeypatch.setattr(sharing_service, "redeem_invite", _raise)
    resp = authed.post("/api/v1/sharing/redeem", json={"token": "stale"})
    assert resp.status_code == 400


def test_redeem_happy_path_returns_recipient_and_linked_copy(authed, monkeypatch):
    result = RedeemResult(
        recipient_id="recip-1",
        recipient_first_name="Ade",
        role=ShareRole.VIEWER,
        copy_key=sharing_copy.LINKED_COPY_KEY,
    )
    monkeypatch.setattr(sharing_service, "redeem_invite", lambda *a, **k: result)
    resp = authed.post("/api/v1/sharing/redeem", json={"token": "good"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["recipient_id"] == "recip-1"
    assert body["recipient_first_name"] == "Ade"
    assert body["copy_key"] == sharing_copy.LINKED_COPY_KEY


def test_roster_route_shape_and_copy_keys(authed, monkeypatch):
    roster = Roster(
        recipient_id="recip-1",
        recipient_first_name="Ade",
        title_copy_key=sharing_copy.ROSTER_TITLE_COPY_KEY,
        empty_copy_key=sharing_copy.ROSTER_EMPTY_COPY_KEY,
        entries=[
            RosterEntry(
                id="m-1",
                kind=RosterStatus.ACTIVE,
                role=ShareRole.VIEWER,
                status=RosterStatus.ACTIVE,
                granted_at=NOW,
            ),
            RosterEntry(
                id="inv-1",
                kind=RosterStatus.PENDING,
                email="ben@example.com",
                role=ShareRole.VIEWER,
                status=RosterStatus.PENDING,
                invited_at=NOW,
                expires_at=EXPIRES,
            ),
        ],
    )
    monkeypatch.setattr(sharing_service, "roster", lambda *a, **k: roster)
    resp = authed.get("/api/v1/sharing/recipients/recip-1/roster")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title_copy_key"] == sharing_copy.ROSTER_TITLE_COPY_KEY
    assert len(body["entries"]) == 2
    # The role is the CODE, for the app to render its own label.
    assert {e["role"] for e in body["entries"]} == {"viewer"}
    assert body["entries"][0]["status"] == "active"
    assert body["entries"][1]["status"] == "pending"


def test_revoke_member_not_found_is_404(authed, monkeypatch):
    monkeypatch.setattr(
        sharing_service,
        "revoke_access",
        lambda *a, **k: RevokeResult(revoked=False, copy_key=sharing_copy.REVOKED_COPY_KEY),
    )
    resp = authed.delete("/api/v1/sharing/recipients/recip-1/members/missing")
    assert resp.status_code == 404


def test_revoke_member_success(authed, monkeypatch):
    monkeypatch.setattr(
        sharing_service,
        "revoke_access",
        lambda *a, **k: RevokeResult(revoked=True, copy_key=sharing_copy.REVOKED_COPY_KEY),
    )
    resp = authed.delete("/api/v1/sharing/recipients/recip-1/members/m-1")
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True


def test_shared_card_route_404_when_no_card(authed, monkeypatch):
    monkeypatch.setattr(sharing_service, "read_shared_card", lambda *a, **k: None)
    resp = authed.get("/api/v1/sharing/recipients/recip-1/card")
    assert resp.status_code == 404


def test_shared_card_route_returns_safe_content(authed, monkeypatch):
    from app.models.card import CardContent

    card = SharedCard(
        recipient_id="recip-1",
        copy_key=sharing_copy.LINKED_COPY_KEY,
        content=CardContent.model_validate(SAFE_CARD_JSON),
    )
    monkeypatch.setattr(sharing_service, "read_shared_card", lambda *a, **k: card)
    resp = authed.get("/api/v1/sharing/recipients/recip-1/card")
    assert resp.status_code == 200
    body = resp.json()
    # The CEILING: only the safe content; first-name-only, no user_id / child_id surfaced.
    assert body["content"]["child_first_name"] == "Ade"
    assert "user_id" not in body["content"] and "child_id" not in body["content"]
    assert body["copy_key"] == sharing_copy.LINKED_COPY_KEY


# ===========================================================================
# SERVICE (real logic + fake Supabase): ownership, consent, the adult block,
# redeem, roster, revoke, the capped card read.
# ===========================================================================


def test_service_invite_records_consent_and_mints(monkeypatch):
    # Owner owns the recipient (child_profile select returns the owned row for both
    # ownership reads); the share RPC returns the new invite id; the invite read-back gives
    # the expiry.
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([OWNED_CHILD]),
            ("rpc", "share_recipient_invite"): FakeResponse("inv-1"),
            ("recipient_invite", "select"): FakeResponse(
                [{"id": "inv-1", "role": "viewer", "expires_at": EXPIRES.isoformat()}]
            ),
        }
    )
    _patch_client(monkeypatch, fake)

    created = sharing_service.invite_viewer(
        AUTHED,
        recipient_id="recip-1",
        email="BEN@example.com",
        role=ShareRole.VIEWER,
        subject_kind=SubjectKind.CHILD,
    )
    assert isinstance(created, InviteCreated)
    assert created.invite_id == "inv-1"
    assert created.token and len(created.token) > 20  # a real strong token
    assert created.expires_at == EXPIRES
    # The consent text was authored by the api (governed) and names the recipient.
    assert "Ade" in created.consent_text
    # A short typable join code is returned in display form (XXXXX-XXXXX) with its copy key,
    # and it normalizes back to a valid 10-char Crockford code.
    from app.engines.sharing.join_code import normalize_join_code
    assert "-" in created.join_code
    assert len(normalize_join_code(created.join_code)) == 10
    assert created.join_code_copy_key == sharing_copy.JOIN_CODE_COPY_KEY
    # The RPC was called with the governed consent text (child path passes it), the
    # normalized join code, and the shortened 48h code TTL.
    rpc_calls = [c for c in fake.calls if c.get("rpc") == "share_recipient_invite"]
    assert rpc_calls and rpc_calls[0]["params"]["p_consent_text"]
    assert rpc_calls[0]["params"]["p_subject_kind"] == "child"
    assert rpc_calls[0]["params"]["p_join_code"] == normalize_join_code(created.join_code)
    assert rpc_calls[0]["params"]["p_ttl_hours"] == 48
    # Email is passed through (the RPC lower-cases it server-side).
    assert rpc_calls[0]["params"]["p_email"] == "BEN@example.com"


def test_service_invite_unowned_recipient_raises(monkeypatch):
    fake = FakeClient({("child_profile", "select"): FakeResponse([])})  # not owned
    _patch_client(monkeypatch, fake)
    with pytest.raises(sharing_service.RecipientNotOwnedError):
        sharing_service.invite_viewer(
            AUTHED, recipient_id="not-mine", email="ben@example.com"
        )


def test_service_adult_share_without_consent_raises_block(monkeypatch):
    # The share RPC raises the adult-block error; the service maps it to the typed error.
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([OWNED_CHILD]),
            ("rpc", "share_recipient_invite"): RuntimeError(
                "adult recipient sharing requires recorded consent first"
            ),
        }
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(sharing_service.AdultConsentRequiredError):
        sharing_service.invite_viewer(
            AUTHED,
            recipient_id="recip-1",
            email="ben@example.com",
            subject_kind=SubjectKind.ADULT,
        )


def test_service_record_adult_consent(monkeypatch):
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([OWNED_CHILD]),
            ("rpc", "record_share_consent"): FakeResponse("consent-1"),
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.record_adult_consent(AUTHED, recipient_id="recip-1")
    assert isinstance(out, ConsentRecorded)
    assert out.consent_id == "consent-1"
    assert out.copy_key == sharing_copy.CONSENT_COPY_KEY_ADULT
    # The recorded text is the governed adult wording.
    rpc = [c for c in fake.calls if c.get("rpc") == "record_share_consent"][0]
    assert rpc["params"]["p_subject_kind"] == "adult"
    assert rpc["params"]["p_consent_text"]


def test_service_redeem_returns_recipient_and_first_name(monkeypatch):
    # redeem RPC -> membership id; membership read-back -> recipient + role; the card read
    # (the only viewer name path) -> first name.
    fake = FakeClient(
        {
            ("rpc", "redeem_recipient_invite"): FakeResponse("m-9"),
            ("recipient_membership", "select"): FakeResponse(
                [{"id": "m-9", "recipient_id": "recip-1", "role": "viewer"}]
            ),
            ("rpc", "get_recipient_card_for_member"): FakeResponse(SAFE_CARD_JSON),
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.redeem_invite(VIEWER, token="good-token")
    assert isinstance(out, RedeemResult)
    assert out.recipient_id == "recip-1"
    assert out.recipient_first_name == "Ade"
    assert out.role == ShareRole.VIEWER
    assert out.copy_key == sharing_copy.LINKED_COPY_KEY


def test_service_redeem_bad_token_raises(monkeypatch):
    fake = FakeClient(
        {("rpc", "redeem_recipient_invite"): RuntimeError("invite already used")}
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(sharing_service.InviteRedeemError):
        sharing_service.redeem_invite(VIEWER, token="used")


def test_service_roster_lists_members_and_pending_invites(monkeypatch):
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([OWNED_CHILD]),
            ("recipient_membership", "select"): FakeResponse(
                [
                    {
                        "id": "m-1",
                        "user_id": "viewer-1",
                        "role": "viewer",
                        "granted_at": NOW.isoformat(),
                    }
                ]
            ),
            ("recipient_invite", "select"): FakeResponse(
                [
                    {
                        "id": "inv-2",
                        "email": "carol@example.com",
                        "role": "viewer",
                        "created_at": NOW.isoformat(),
                        "expires_at": EXPIRES.isoformat(),
                    }
                ]
            ),
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.roster(AUTHED, recipient_id="recip-1")
    assert isinstance(out, Roster)
    assert out.recipient_first_name == "Ade"
    assert out.title_copy_key == sharing_copy.ROSTER_TITLE_COPY_KEY
    kinds = {e.kind for e in out.entries}
    assert kinds == {RosterStatus.ACTIVE, RosterStatus.PENDING}
    # The pending entry carries the invited email; the active entry does not leak it.
    pending = [e for e in out.entries if e.kind == RosterStatus.PENDING][0]
    assert pending.email == "carol@example.com"
    # BOUNDED (the every-list-is-capped rule): a roster is a handful of members + pending
    # invites, but BOTH reads carry a safety `.limit(...)` as the runaway-read backstop.
    from app.services.pagination import MAX_BOUNDED_ROWS

    member_select = next(
        c for c in fake.calls if c["table"] == "recipient_membership" and c["op"] == "select"
    )
    invite_select = next(
        c for c in fake.calls if c["table"] == "recipient_invite" and c["op"] == "select"
    )
    assert member_select["limit"] == MAX_BOUNDED_ROWS
    assert invite_select["limit"] == MAX_BOUNDED_ROWS


def test_service_revoke_access_soft_revokes_and_excludes_owner(monkeypatch):
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([OWNED_CHILD]),
            ("recipient_membership", "update"): FakeResponse([{"id": "m-1"}]),
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.revoke_access(AUTHED, recipient_id="recip-1", membership_id="m-1")
    assert out.revoked is True
    # The update filtered out role='owner' (an owner row is never revoked through here) and
    # stamped revoked_at.
    upd = [c for c in fake.calls if c["table"] == "recipient_membership" and c["op"] == "update"][0]
    assert ("role", "owner") in upd["filters"]  # neq('role','owner') recorded as a filter
    assert "revoked_at" in upd["payload"]


def test_service_revoke_access_missing_is_not_revoked(monkeypatch):
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([OWNED_CHILD]),
            ("recipient_membership", "update"): FakeResponse([]),  # nothing matched
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.revoke_access(AUTHED, recipient_id="recip-1", membership_id="nope")
    assert out.revoked is False


def test_service_read_shared_card_is_the_ceiling(monkeypatch):
    # The capped read goes through get_recipient_card_for_member ONLY; the service never
    # touches child_profile / lci_snapshot / alert_record / pulse_record. The fake scripts
    # ONLY the RPC, so if the service tried any other table the FakeClient would raise
    # "No scripted Supabase response".
    fake = FakeClient({("rpc", "get_recipient_card_for_member"): FakeResponse(SAFE_CARD_JSON)})
    _patch_client(monkeypatch, fake)
    out = sharing_service.read_shared_card(VIEWER, recipient_id="recip-1")
    assert isinstance(out, SharedCard)
    assert out.content.child_first_name == "Ade"
    assert out.copy_key == sharing_copy.LINKED_COPY_KEY
    # The ONLY data path used was the membership-gated RPC.
    assert [c for c in fake.calls if c.get("rpc")] == [
        {"rpc": "get_recipient_card_for_member", "params": {"p_child_id": "recip-1"}}
    ]


def test_service_read_shared_card_none_when_not_a_member(monkeypatch):
    # A non-member / no-live-card gets NULL from the RPC -> None (the route maps to 404,
    # never the profile).
    fake = FakeClient({("rpc", "get_recipient_card_for_member"): FakeResponse(None)})
    _patch_client(monkeypatch, fake)
    assert sharing_service.read_shared_card(VIEWER, recipient_id="recip-1") is None


def test_service_shared_with_me_lists_recipients_first_name_only(monkeypatch):
    # The viewer's non-owner active memberships, each resolved to a first name via the capped
    # card read.
    fake = FakeClient(
        {
            ("recipient_membership", "select"): FakeResponse(
                [{"recipient_id": "recip-1", "role": "viewer", "granted_at": NOW.isoformat()}]
            ),
            ("rpc", "get_recipient_card_for_member"): FakeResponse(SAFE_CARD_JSON),
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.shared_with_me(VIEWER)
    assert isinstance(out, SharedWithMe)
    assert len(out.recipients) == 1
    r = out.recipients[0]
    assert isinstance(r, SharedRecipient)
    assert r.recipient_id == "recip-1"
    assert r.recipient_first_name == "Ade"  # first name only, via the ceiling read
    assert r.copy_key == sharing_copy.LINKED_COPY_KEY
    # BOUNDED (the every-list-is-capped rule): a caller is shared a small set of recipients,
    # but the membership read still carries a safety `.limit(...)` as the runaway-read backstop.
    from app.services.pagination import MAX_BOUNDED_ROWS

    member_select = next(
        c for c in fake.calls if c["table"] == "recipient_membership" and c["op"] == "select"
    )
    assert member_select["limit"] == MAX_BOUNDED_ROWS


# ===========================================================================
# REDEEM-BY-CODE (the short typable join code, the 2026-06-13 board verdict).
# Route wiring, the NO-ORACLE generic 400 across every failure reason, the
# service funnelling into the SAME redeem core, and the rate-limit decoration.
# ===========================================================================


def test_redeem_by_code_happy_path_returns_recipient_and_linked_copy(authed, monkeypatch):
    result = RedeemResult(
        recipient_id="recip-1",
        recipient_first_name="Ade",
        role=ShareRole.VIEWER,
        copy_key=sharing_copy.LINKED_COPY_KEY,
    )
    captured = {}

    def _fake(user, *, join_code):
        captured["join_code"] = join_code
        return result

    monkeypatch.setattr(sharing_service, "redeem_invite_by_code", _fake)
    # The app sends the code in display form; the service normalizes it.
    resp = authed.post("/api/v1/sharing/redeem-by-code", json={"join_code": "KJBJQ-DVF61"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["recipient_id"] == "recip-1"
    assert body["recipient_first_name"] == "Ade"
    assert body["copy_key"] == sharing_copy.LINKED_COPY_KEY
    assert captured["join_code"] == "KJBJQ-DVF61"


def test_redeem_by_code_requires_auth(client):
    # No dependency override: the real current-user dep runs and rejects (no token -> 401).
    resp = client.post("/api/v1/sharing/redeem-by-code", json={"join_code": "KJBJQ-DVF61"})
    assert resp.status_code == 401


def test_redeem_by_code_is_a_generic_400_with_no_oracle(authed, monkeypatch):
    # THE NO-ORACLE GUARANTEE (the board's load-bearing security property): EVERY failure reason
    # (unknown code / expired / already redeemed / revoked / wrong signed-in email / malformed)
    # produces the SAME status AND the SAME body, so an attacker cannot tell "code does not
    # exist" from "code exists but you are not the bound email". The service raises one error
    # type (InviteRedeemError) for all of them; here we drive several distinct underlying reasons
    # and assert the boundary response is byte-for-byte identical.
    reasons = [
        "unknown code",
        "invite expired",
        "invite already used",
        "invite revoked",
        "invite is for a different email",
        "malformed",
    ]
    responses = []
    for reason in reasons:
        def _raise(*a, _r=reason, **k):
            raise sharing_service.InviteRedeemError(_r)

        monkeypatch.setattr(sharing_service, "redeem_invite_by_code", _raise)
        resp = authed.post("/api/v1/sharing/redeem-by-code", json={"join_code": "ZZZZZ-ZZZZZ"})
        responses.append((resp.status_code, resp.json()))

    # Identical status AND body across every reason: no oracle leaks which failed.
    statuses = {r[0] for r in responses}
    bodies = {tuple(sorted(r[1].items())) for r in responses}
    assert statuses == {400}, statuses
    assert len(bodies) == 1, f"the 400 body differs across failure reasons (an oracle!): {bodies}"
    # And it does not echo the underlying reason.
    only_body = responses[0][1]
    for reason in reasons:
        assert reason not in str(only_body)


@pytest.fixture
def limited_by_code():
    """Turn the limiter ON for one test with a clean store; restore OFF afterward.

    slowapi stores the per-route Limit config in the decorator closure (not an introspectable
    attribute), so the ONLY robust way to prove the route carries a limiter is BEHAVIORAL: fire
    requests and assert the 429. Mirrors the `limited` fixture in tests/test_rate_limit.py.
    """
    from app.rate_limit import limiter

    limiter._storage.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter._storage.reset()


def test_redeem_by_code_carries_per_ip_limiter(authed, limited_by_code, monkeypatch):
    # A short code MUST be throttled (the board): the by-code route carries the SAME per-IP
    # REDEEM_LIMITS (5/min;30/hr) as the token redeem. The 6th attempt from one IP is 429. We
    # stub the service so the route returns fast and the limiter is what we are exercising.
    monkeypatch.setattr(
        sharing_service,
        "redeem_invite_by_code",
        lambda *a, **k: (_ for _ in ()).throw(sharing_service.InviteRedeemError("x")),
    )
    headers = {"X-Forwarded-For": "77.77.77.77"}
    body = {"join_code": "ZZZZZ-ZZZZZ"}
    for i in range(5):  # the REDEEM_LIMITS per-minute budget (per IP)
        r = authed.post("/api/v1/sharing/redeem-by-code", json=body, headers=headers)
        assert r.status_code == 400, f"attempt {i} should pass the limiter (got {r.status_code})"
    blocked = authed.post("/api/v1/sharing/redeem-by-code", json=body, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many attempts. Please wait a moment and try again."}
    assert blocked.headers.get("Retry-After") == "60"


def test_redeem_by_code_carries_per_token_limiter(authed, limited_by_code, monkeypatch):
    # The route ALSO carries the per-token REDEEM_TOKEN_LIMIT (20/min). To exercise it
    # INDEPENDENTLY of the per-IP limit, vary the IP each request (so per-IP never trips) while
    # the bearer token stays constant (the authed override fixes the user, but the token bucket
    # keys on the Authorization header, which the TestClient does not send; so we set it). The
    # 21st request on one token is 429 even though every IP is fresh.
    monkeypatch.setattr(
        sharing_service,
        "redeem_invite_by_code",
        lambda *a, **k: (_ for _ in ()).throw(sharing_service.InviteRedeemError("x")),
    )
    token_headers = {"Authorization": "Bearer one-fixed-token"}
    body = {"join_code": "ZZZZZ-ZZZZZ"}
    for i in range(20):  # the REDEEM_TOKEN_LIMIT per-minute budget (per token)
        h = {**token_headers, "X-Forwarded-For": f"88.88.{i}.{i}"}  # fresh IP each time
        r = authed.post("/api/v1/sharing/redeem-by-code", json=body, headers=h)
        assert r.status_code == 400, f"attempt {i} passes the per-IP limit (got {r.status_code})"
    blocked = authed.post(
        "/api/v1/sharing/redeem-by-code",
        json=body,
        headers={**token_headers, "X-Forwarded-For": "88.88.250.250"},
    )
    assert blocked.status_code == 429  # the per-token cap fired though every IP was fresh


def test_service_redeem_by_code_funnels_into_the_same_core(monkeypatch):
    # The by-code service path normalizes the typed code, calls redeem_recipient_invite_by_code,
    # and funnels into the SAME read-back the token path uses: redeem RPC -> membership id;
    # membership read-back -> recipient + role; the capped card read -> first name.
    fake = FakeClient(
        {
            ("rpc", "redeem_recipient_invite_by_code"): FakeResponse("m-9"),
            ("recipient_membership", "select"): FakeResponse(
                [{"id": "m-9", "recipient_id": "recip-1", "role": "viewer"}]
            ),
            ("rpc", "get_recipient_card_for_member"): FakeResponse(SAFE_CARD_JSON),
        }
    )
    _patch_client(monkeypatch, fake)
    out = sharing_service.redeem_invite_by_code(VIEWER, join_code="kjbjq-dvf61")
    assert isinstance(out, RedeemResult)
    assert out.recipient_id == "recip-1"
    assert out.recipient_first_name == "Ade"
    assert out.role == ShareRole.VIEWER
    assert out.copy_key == sharing_copy.LINKED_COPY_KEY
    # The RPC was called with the NORMALIZED code (uppercase, no dashes), not the typed form.
    rpc = [c for c in fake.calls if c.get("rpc") == "redeem_recipient_invite_by_code"][0]
    assert rpc["params"]["p_join_code"] == "KJBJQDVF61"


def test_service_redeem_by_code_malformed_raises_without_touching_the_db(monkeypatch):
    # A malformed code (normalization fails) is the SAME generic failure as an unknown one, and
    # it never reaches the RPC (the FakeClient would raise if any call were attempted).
    fake = FakeClient({})  # nothing scripted: any DB/RPC call would AssertionError
    _patch_client(monkeypatch, fake)
    with pytest.raises(sharing_service.InviteRedeemError):
        sharing_service.redeem_invite_by_code(VIEWER, join_code="not-a-valid-code!!")
    # Proven no RPC was attempted.
    assert not [c for c in fake.calls if c.get("rpc")]


def test_service_redeem_by_code_rpc_failure_raises_redeem_error(monkeypatch):
    # The by-code RPC raises ONE uniform error for any reason (unknown/expired/used/revoked/
    # wrong-email); the service wraps it as InviteRedeemError (the route -> generic 400).
    fake = FakeClient(
        {
            ("rpc", "redeem_recipient_invite_by_code"): RuntimeError(
                "invite could not be redeemed"
            )
        }
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(sharing_service.InviteRedeemError):
        sharing_service.redeem_invite_by_code(VIEWER, join_code="ZZZZZ-ZZZZZ")
