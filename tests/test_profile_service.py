"""No-DB unit tests for the profile data service (app/services/profile).

The service's only I/O is the Supabase client; both client factories
(get_anon_client RLS-scoped, get_service_client admin) are monkeypatched to the
FakeClient in tests/fakes_supabase, so the suite never reaches a live Supabase
(blocked in the sandbox; the task requires mocking the client). These pin the
data behaviour: get-or-create, the service-role create path, updates, the child
read/create/update, the onboarding write, and the Enum -> code serialization.
"""

from typing import Optional

import app.services.profile as svc
from app.auth import AuthedUser
from tests.fakes_supabase import FakeClient, FakeResponse

USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")


def _patch_clients(monkeypatch, anon: FakeClient, service: Optional[FakeClient] = None):
    """Route both client factories to fakes. Records the token the anon client got."""
    captured = {"anon_token": "UNSET"}

    def fake_anon(access_token=None):
        captured["anon_token"] = access_token
        return anon

    monkeypatch.setattr(svc, "get_anon_client", fake_anon)
    if service is not None:
        monkeypatch.setattr(svc, "get_service_client", lambda: service)
    return captured


# ---------------------------------------------------------------------------
# user_profile
# ---------------------------------------------------------------------------


def test_get_or_create_returns_existing_profile_without_service_client(monkeypatch):
    existing = {"id": "u-1", "email": "ada@example.com", "first_name": "Ada"}
    anon = FakeClient({("user_profile", "select"): FakeResponse(existing)})
    # No service client provided: if the code tried to create, it would fail.
    captured = _patch_clients(monkeypatch, anon)

    result = svc.get_or_create_profile(USER)

    assert result == existing
    # The RLS-scoped client was built with the caller's token.
    assert captured["anon_token"] == "tok-abc"


def test_get_or_create_creates_profile_via_service_client_when_missing(monkeypatch):
    created = {"id": "u-1", "email": "ada@example.com", "first_name": "ada"}
    anon = FakeClient({("user_profile", "select"): FakeResponse(None)})
    service = FakeClient({("user_profile", "insert"): FakeResponse([created])})
    _patch_clients(monkeypatch, anon, service)

    result = svc.get_or_create_profile(USER)

    assert result["id"] == "u-1"
    # The insert went through the SERVICE client (RLS bypassed by design) and was
    # scoped to the caller's id; first_name fell back to the email local-part.
    insert_call = service.calls[0]
    assert insert_call["op"] == "insert"
    assert insert_call["payload"]["id"] == "u-1"
    assert insert_call["payload"]["first_name"] == "ada"


def test_get_or_create_uses_supplied_first_name(monkeypatch):
    anon = FakeClient({("user_profile", "select"): FakeResponse(None)})
    created = {"id": "u-1", "first_name": "Bisi"}
    service = FakeClient({("user_profile", "insert"): FakeResponse([created])})
    _patch_clients(monkeypatch, anon, service)

    svc.get_or_create_profile(USER, first_name="Bisi")
    assert service.calls[0]["payload"]["first_name"] == "Bisi"


def test_default_first_name_falls_back_to_coordinator_without_email():
    user = AuthedUser(id="u-9", email=None, access_token="t")
    assert svc._default_first_name(user) == "Coordinator"


def test_update_profile_returns_updated_row(monkeypatch):
    updated = {"id": "u-1", "first_name": "Ada", "onboarding_complete": True}
    anon = FakeClient({("user_profile", "update"): FakeResponse([updated])})
    _patch_clients(monkeypatch, anon)

    result = svc.update_profile(USER, {"onboarding_complete": True})

    assert result == updated
    call = anon.calls[0]
    assert call["op"] == "update"
    assert ("id", "u-1") in call["filters"]  # scoped to the caller's row


def test_update_profile_returns_none_when_no_row(monkeypatch):
    anon = FakeClient({("user_profile", "update"): FakeResponse([])})
    _patch_clients(monkeypatch, anon)
    assert svc.update_profile(USER, {"first_name": "X"}) is None


# ---------------------------------------------------------------------------
# child_profile
# ---------------------------------------------------------------------------


def test_get_child_returns_none_when_absent(monkeypatch):
    anon = FakeClient({("child_profile", "select"): FakeResponse([])})
    _patch_clients(monkeypatch, anon)
    assert svc.get_child(USER) is None


def test_get_child_returns_row_and_scopes_by_user(monkeypatch):
    row = {"id": "c-1", "user_id": "u-1", "name": "Sam"}
    anon = FakeClient({("child_profile", "select"): FakeResponse([row])})
    _patch_clients(monkeypatch, anon)

    result = svc.get_child(USER)

    assert result == row
    assert ("user_id", "u-1") in anon.calls[0]["filters"]


def test_create_child_sets_user_id_from_session_not_client(monkeypatch):
    created = {"id": "c-1", "user_id": "u-1", "name": "Sam"}
    anon = FakeClient({("child_profile", "insert"): FakeResponse([created])})
    _patch_clients(monkeypatch, anon)

    # Even if a forged user_id is passed in fields, the service overrides it.
    result = svc.create_child(USER, {"name": "Sam", "user_id": "ATTACKER"})

    assert result == created
    assert anon.calls[0]["payload"]["user_id"] == "u-1"


def test_create_child_serializes_enum_tags_to_codes(monkeypatch):
    from app.models.child_profile import SupportLevelCode, Tag

    created = {"id": "c-1", "user_id": "u-1", "name": "Sam"}
    anon = FakeClient({("child_profile", "insert"): FakeResponse([created])})
    _patch_clients(monkeypatch, anon)

    svc.create_child(
        USER,
        {
            "name": "Sam",
            "support_level_code": SupportLevelCode.HIGH,
            "tags": [Tag.SN_NOISE, Tag.TR_CHANGE],
        },
    )

    payload = anon.calls[0]["payload"]
    # Enums are stored as their plain string codes (text / text[] columns).
    assert payload["support_level_code"] == "SL-HIGH"
    assert payload["tags"] == ["SN-NOISE", "TR-CHANGE"]


def test_update_child_scopes_by_id_and_user(monkeypatch):
    updated = {"id": "c-1", "user_id": "u-1", "name": "Samuel"}
    anon = FakeClient({("child_profile", "update"): FakeResponse([updated])})
    _patch_clients(monkeypatch, anon)

    result = svc.update_child(USER, "c-1", {"name": "Samuel"})

    assert result == updated
    filters = anon.calls[0]["filters"]
    assert ("id", "c-1") in filters
    assert ("user_id", "u-1") in filters  # cannot update another user's row


def test_update_child_returns_none_for_unowned_id(monkeypatch):
    # RLS makes another user's row invisible: the update matches nothing.
    anon = FakeClient({("child_profile", "update"): FakeResponse([])})
    _patch_clients(monkeypatch, anon)
    assert svc.update_child(USER, "c-forged", {"name": "X"}) is None


# ---------------------------------------------------------------------------
# onboarding write
# ---------------------------------------------------------------------------


def test_complete_onboarding_creates_child_when_none_and_marks_complete(monkeypatch):
    profile_row = {"id": "u-1", "first_name": "Ada", "onboarding_complete": True}
    child_row = {"id": "c-1", "user_id": "u-1", "name": "Sam"}
    # Scripted in call order: profile select (exists), child select (none),
    # child insert, profile update.
    anon = FakeClient(
        {
            ("user_profile", "select"): [FakeResponse({"id": "u-1", "first_name": "Ada"})],
            ("child_profile", "select"): FakeResponse([]),
            ("child_profile", "insert"): FakeResponse([child_row]),
            ("user_profile", "update"): FakeResponse([profile_row]),
        }
    )
    _patch_clients(monkeypatch, anon)

    payload = {
        "name": "Sam",
        "age_band": "6-8",
        "support_level_code": "SL-MED",
        "tags": ["SN-NOISE", "CM-MIXED"],
        "first_activity": {"chapter": "mornings", "activity": "school-run"},
    }
    result = svc.complete_onboarding(USER, payload)

    assert result["profile"]["onboarding_complete"] is True
    assert result["child"] == child_row
    # The profile update flipped onboarding_complete via the RLS-scoped client.
    update_calls = [c for c in anon.calls if c["table"] == "user_profile" and c["op"] == "update"]
    assert update_calls and update_calls[0]["payload"] == {"onboarding_complete": True}
    # first_activity is carried but NOT written as a child column (no scoring here).
    insert_calls = [
        c for c in anon.calls if c["table"] == "child_profile" and c["op"] == "insert"
    ]
    assert "first_activity" not in insert_calls[0]["payload"]


def test_complete_onboarding_updates_existing_child(monkeypatch):
    existing_child = {"id": "c-1", "user_id": "u-1", "name": "Old"}
    updated_child = {"id": "c-1", "user_id": "u-1", "name": "Sam"}
    profile_row = {"id": "u-1", "first_name": "Ada", "onboarding_complete": True}
    anon = FakeClient(
        {
            ("user_profile", "select"): [FakeResponse({"id": "u-1", "first_name": "Ada"})],
            ("child_profile", "select"): FakeResponse([existing_child]),
            ("child_profile", "update"): FakeResponse([updated_child]),
            ("user_profile", "update"): FakeResponse([profile_row]),
        }
    )
    _patch_clients(monkeypatch, anon)

    payload = {"name": "Sam", "support_level_code": "SL-LOW", "tags": []}
    result = svc.complete_onboarding(USER, payload)

    assert result["child"] == updated_child
    # An existing recipient is UPDATED, not duplicated (one active per user, MVP).
    update_child_calls = [
        c for c in anon.calls if c["table"] == "child_profile" and c["op"] == "update"
    ]
    assert update_child_calls and ("id", "c-1") in update_child_calls[0]["filters"]
