"""No-DB unit tests for the account data service (app/services/account).

The service's only I/O is the RLS-scoped Supabase anon client, monkeypatched to the
FakeClient in tests/fakes_supabase (same seam as test_profile_service), so the suite never
reaches a live Supabase. These pin: the soft-delete state read (is_account_deleted), the
export gathering the caller's own rows scoped by user_id across every user-owned table, and
the soft-delete write setting user_profile.deleted_at on the caller's own row.
"""

import app.services.account as svc
from app.auth import AuthedUser
from tests.fakes_supabase import FakeClient, FakeResponse

USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")


def _patch_anon(monkeypatch, anon: FakeClient):
    """Route get_anon_client to the fake and record the token it was built with."""
    captured = {"anon_token": "UNSET"}

    def fake_anon(access_token=None):
        captured["anon_token"] = access_token
        return anon

    monkeypatch.setattr(svc, "get_anon_client", fake_anon)
    return captured


# ---------------------------------------------------------------------------
# is_account_deleted (the access-block read)
# ---------------------------------------------------------------------------


def test_is_account_deleted_false_when_deleted_at_null(monkeypatch):
    anon = FakeClient({("user_profile", "select"): FakeResponse({"deleted_at": None})})
    captured = _patch_anon(monkeypatch, anon)

    assert svc.is_account_deleted(USER) is False
    # Read under the caller's token, scoped to the caller's own row.
    assert captured["anon_token"] == "tok-abc"
    assert ("id", "u-1") in anon.calls[0]["filters"]


def test_is_account_deleted_true_when_deleted_at_set(monkeypatch):
    anon = FakeClient(
        {("user_profile", "select"): FakeResponse({"deleted_at": "2026-06-12T10:00:00+00:00"})}
    )
    _patch_anon(monkeypatch, anon)
    assert svc.is_account_deleted(USER) is True


def test_is_account_deleted_false_when_no_profile_row(monkeypatch):
    # A fresh sign-up with no profile row yet is treated as active (nothing closed).
    anon = FakeClient({("user_profile", "select"): FakeResponse(None)})
    _patch_anon(monkeypatch, anon)
    assert svc.is_account_deleted(USER) is False


# ---------------------------------------------------------------------------
# export_account (RLS-scoped, caller's own rows only)
# ---------------------------------------------------------------------------


def test_export_gathers_callers_rows_scoped_by_user(monkeypatch):
    profile = {"id": "u-1", "email": "ada@example.com", "first_name": "Ada"}
    child = {"id": "c-1", "user_id": "u-1", "name": "Sam"}
    activity = {"id": "a-1", "user_id": "u-1", "activity_name": "School run"}
    pulse = {"id": "p-1", "user_id": "u-1", "outcome_code": "well"}
    snapshot = {"id": "s-1", "user_id": "u-1", "score": 70}
    alert = {"id": "al-1", "user_id": "u-1", "level": 1}
    card = {"id": "cd-1", "user_id": "u-1", "token": "tok"}
    anon = FakeClient(
        {
            ("user_profile", "select"): FakeResponse(profile),
            ("child_profile", "select"): FakeResponse([child]),
            ("activity_record", "select"): FakeResponse([activity]),
            ("pulse_record", "select"): FakeResponse([pulse]),
            ("lci_snapshot", "select"): FakeResponse([snapshot]),
            ("alert_record", "select"): FakeResponse([alert]),
            ("card_record", "select"): FakeResponse([card]),
        }
    )
    captured = _patch_anon(monkeypatch, anon)

    document = svc.export_account(USER)

    # The RLS-scoped client carried the caller's token.
    assert captured["anon_token"] == "tok-abc"
    # The document carries every user-owned table, profile as a single object.
    assert document["user_profile"] == profile
    assert document["child_profile"] == [child]
    assert document["activity_record"] == [activity]
    assert document["pulse_record"] == [pulse]
    assert document["lci_snapshot"] == [snapshot]
    assert document["alert_record"] == [alert]
    assert document["card_record"] == [card]
    # EVERY record/child read was scoped to the caller (user_id == u-1); the profile read
    # was scoped by id == u-1. Two guards (RLS + the explicit filter) keep it the caller's.
    record_calls = [c for c in anon.calls if c["table"] != "user_profile"]
    assert record_calls, "expected per-table reads"
    for call in record_calls:
        assert ("user_id", "u-1") in call["filters"]
    profile_call = next(c for c in anon.calls if c["table"] == "user_profile")
    assert ("id", "u-1") in profile_call["filters"]


def test_export_returns_empty_lists_when_user_has_no_records(monkeypatch):
    anon = FakeClient(
        {
            ("user_profile", "select"): FakeResponse(None),
            ("child_profile", "select"): FakeResponse([]),
            ("activity_record", "select"): FakeResponse([]),
            ("pulse_record", "select"): FakeResponse([]),
            ("lci_snapshot", "select"): FakeResponse([]),
            ("alert_record", "select"): FakeResponse([]),
            ("card_record", "select"): FakeResponse([]),
        }
    )
    _patch_anon(monkeypatch, anon)

    document = svc.export_account(USER)
    assert document["user_profile"] is None
    for table in ("child_profile", "activity_record", "pulse_record", "lci_snapshot",
                  "alert_record", "card_record"):
        assert document[table] == []


# ---------------------------------------------------------------------------
# soft_delete_account (sets deleted_at on the caller's own row; idempotent)
# ---------------------------------------------------------------------------


def test_soft_delete_sets_deleted_at_on_callers_own_row(monkeypatch):
    updated = {"id": "u-1", "deleted_at": "2026-06-12T10:00:00+00:00"}
    anon = FakeClient({("user_profile", "update"): FakeResponse([updated])})
    captured = _patch_anon(monkeypatch, anon)

    result = svc.soft_delete_account(USER)

    assert result["deleted"] is True
    assert result["deleted_at"] == "2026-06-12T10:00:00+00:00"
    assert captured["anon_token"] == "tok-abc"
    call = anon.calls[0]
    assert call["op"] == "update"
    # The write sets deleted_at and is scoped to the caller's own row (cannot close another).
    assert "deleted_at" in call["payload"]
    assert call["payload"]["deleted_at"] is not None
    assert ("id", "u-1") in call["filters"]


def test_soft_delete_is_idempotent_returns_confirmation_even_if_no_row_echoed(monkeypatch):
    # Some PostgREST configs return no representation on update; the service still confirms
    # (it falls back to the timestamp it sent), so a repeat/echo-less delete still succeeds.
    anon = FakeClient({("user_profile", "update"): FakeResponse([])})
    _patch_anon(monkeypatch, anon)

    result = svc.soft_delete_account(USER)
    assert result["deleted"] is True
    assert result["deleted_at"]  # a non-empty ISO timestamp
