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
        "/api/v3/sharing/invites",
        json={"recipient_id": "recip-1", "email": "ben@example.com"},
    )
    assert resp.status_code == 401


def test_invite_happy_path_returns_token_and_governed_copy(authed, monkeypatch):
    created = InviteCreated(
        invite_id="inv-1",
        token="tok-share",
        role=ShareRole.VIEWER,
        expires_at=EXPIRES,
        copy_key=sharing_copy.INVITE_COPY_KEY,
        consent_text="I confirm I have the authority to share Ade's support information ...",
    )
    monkeypatch.setattr(sharing_service, "invite_viewer", lambda *a, **k: created)

    resp = authed.post(
        "/api/v3/sharing/invites",
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


def test_invite_unowned_recipient_is_404(authed, monkeypatch):
    def _raise(*a, **k):
        raise sharing_service.RecipientNotOwnedError("nope")

    monkeypatch.setattr(sharing_service, "invite_viewer", _raise)
    resp = authed.post(
        "/api/v3/sharing/invites",
        json={"recipient_id": "not-mine", "email": "ben@example.com"},
    )
    assert resp.status_code == 404


def test_invite_adult_without_consent_is_409(authed, monkeypatch):
    def _raise(*a, **k):
        raise sharing_service.AdultConsentRequiredError("needs consent")

    monkeypatch.setattr(sharing_service, "invite_viewer", _raise)
    resp = authed.post(
        "/api/v3/sharing/invites",
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
    resp = authed.post("/api/v3/sharing/redeem", json={"token": "stale"})
    assert resp.status_code == 400


def test_redeem_happy_path_returns_recipient_and_linked_copy(authed, monkeypatch):
    result = RedeemResult(
        recipient_id="recip-1",
        recipient_first_name="Ade",
        role=ShareRole.VIEWER,
        copy_key=sharing_copy.LINKED_COPY_KEY,
    )
    monkeypatch.setattr(sharing_service, "redeem_invite", lambda *a, **k: result)
    resp = authed.post("/api/v3/sharing/redeem", json={"token": "good"})
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
    resp = authed.get("/api/v3/sharing/recipients/recip-1/roster")
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
    resp = authed.delete("/api/v3/sharing/recipients/recip-1/members/missing")
    assert resp.status_code == 404


def test_revoke_member_success(authed, monkeypatch):
    monkeypatch.setattr(
        sharing_service,
        "revoke_access",
        lambda *a, **k: RevokeResult(revoked=True, copy_key=sharing_copy.REVOKED_COPY_KEY),
    )
    resp = authed.delete("/api/v3/sharing/recipients/recip-1/members/m-1")
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True


def test_shared_card_route_404_when_no_card(authed, monkeypatch):
    monkeypatch.setattr(sharing_service, "read_shared_card", lambda *a, **k: None)
    resp = authed.get("/api/v3/sharing/recipients/recip-1/card")
    assert resp.status_code == 404


def test_shared_card_route_returns_safe_content(authed, monkeypatch):
    from app.models.card import CardContent

    card = SharedCard(
        recipient_id="recip-1",
        copy_key=sharing_copy.LINKED_COPY_KEY,
        content=CardContent.model_validate(SAFE_CARD_JSON),
    )
    monkeypatch.setattr(sharing_service, "read_shared_card", lambda *a, **k: card)
    resp = authed.get("/api/v3/sharing/recipients/recip-1/card")
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
    # The RPC was called with the governed consent text (child path passes it).
    rpc_calls = [c for c in fake.calls if c.get("rpc") == "share_recipient_invite"]
    assert rpc_calls and rpc_calls[0]["params"]["p_consent_text"]
    assert rpc_calls[0]["params"]["p_subject_kind"] == "child"
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
