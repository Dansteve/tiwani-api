"""No-DB unit tests for the account data service (app/services/account).

The service's only I/O is the RLS-scoped Supabase anon client, monkeypatched to the
FakeClient in tests/fakes_supabase (same seam as test_profile_service), so the suite never
reaches a live Supabase. These pin: the soft-delete state read (is_account_deleted, including
its fail-open behaviour when the deleted_at read itself errors), the export gathering the
caller's own rows scoped by user_id across every user-owned table, the soft-delete write
setting user_profile.deleted_at on the caller's own row AND revoking the caller's active
cards, the account-status read (the computed 90-day recovery window), and the reactivation
write (clearing deleted_at inside the window, refusing past it).
"""

from datetime import datetime, timedelta, timezone

import pytest

import app.services.account as svc
from app.auth import AuthedUser
from tests.fakes_supabase import FakeClient, FakeQuery, FakeResponse

USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")


class _RaisingQuery(FakeQuery):
    """A FakeQuery whose execute() RAISES, simulating a failed deleted_at read.

    Reuses the recording fluent builder (select/eq/maybe_single all record as usual) but
    blows up at the terminal, the way PostgREST hard-errors on a select of a column that does
    not exist (the deleted_at column before migration 0013 was applied) or on a transient
    Supabase error. The call is still logged before raising so a test could assert it was
    attempted.
    """

    def execute(self) -> FakeResponse:
        self._log.append(
            {
                "table": self._table,
                "op": self._op,
                "payload": self._payload,
                "filters": list(self._filters),
                "single": self._single,
            }
        )
        raise RuntimeError("column user_profile.deleted_at does not exist")


class _RaisingClient(FakeClient):
    """A FakeClient whose table() reads RAISE, to exercise _read_deleted_at's fail-open path."""

    def table(self, name: str) -> FakeQuery:
        return _RaisingQuery(name, self.calls, self.scripts)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(days: float) -> str:
    """An ISO timestamp `days` in the past (for the recovery-window math)."""
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


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


def test_is_account_deleted_fails_open_to_active_when_read_raises(monkeypatch, caplog):
    # Fail-open: if reading deleted_at ERRORS (e.g. the column is missing because migration
    # 0013 has not been applied, or a transient Supabase error), the account is treated as
    # ACTIVE rather than 500-ing the request. A soft-delete read runs in get_current_user on
    # EVERY data request, so an error here must never take down the authenticated api.
    anon = _RaisingClient({})  # no scripts needed: execute() raises before consulting them
    _patch_anon(monkeypatch, anon)

    import logging

    with caplog.at_level(logging.WARNING):
        assert svc.is_account_deleted(USER) is False

    # The swallowed failure is observable, logged at WARNING (not silently dropped).
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)
    # The read was still attempted under the caller's token (it did not short-circuit).
    assert anon.calls, "expected the deleted_at read to be attempted before failing open"


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
    anon = FakeClient(
        {
            ("user_profile", "update"): FakeResponse([updated]),
            # soft_delete also revokes the caller's active cards (the same revoked_at marker
            # the public token read checks); script the bulk card update.
            ("card_record", "update"): FakeResponse([]),
        }
    )
    captured = _patch_anon(monkeypatch, anon)

    result = svc.soft_delete_account(USER)

    assert result["deleted"] is True
    assert result["deleted_at"] == "2026-06-12T10:00:00+00:00"
    assert captured["anon_token"] == "tok-abc"
    profile_update = next(
        c for c in anon.calls if c["table"] == "user_profile" and c["op"] == "update"
    )
    # The write sets deleted_at and is scoped to the caller's own row (cannot close another).
    assert "deleted_at" in profile_update["payload"]
    assert profile_update["payload"]["deleted_at"] is not None
    assert ("id", "u-1") in profile_update["filters"]


def test_soft_delete_is_idempotent_returns_confirmation_even_if_no_row_echoed(monkeypatch):
    # Some PostgREST configs return no representation on update; the service still confirms
    # (it falls back to the timestamp it sent), so a repeat/echo-less delete still succeeds.
    anon = FakeClient(
        {
            ("user_profile", "update"): FakeResponse([]),
            ("card_record", "update"): FakeResponse([]),
        }
    )
    _patch_anon(monkeypatch, anon)

    result = svc.soft_delete_account(USER)
    assert result["deleted"] is True
    assert result["deleted_at"]  # a non-empty ISO timestamp


def test_soft_delete_revokes_the_callers_active_cards(monkeypatch):
    # Part C: closing the account revokes the caller's still-active Continuity Cards so a
    # closed account stops exposing the recipient's data via a public share link. It reuses
    # the existing revoked_at marker (set only on not-yet-revoked rows), RLS-scoped to the
    # caller's own cards.
    anon = FakeClient(
        {
            ("user_profile", "update"): FakeResponse([{"id": "u-1", "deleted_at": _ago(0)}]),
            ("card_record", "update"): FakeResponse([]),
        }
    )
    _patch_anon(monkeypatch, anon)

    svc.soft_delete_account(USER)

    card_update = next(
        c for c in anon.calls if c["table"] == "card_record" and c["op"] == "update"
    )
    # It SETS revoked_at (the marker the public token resolver checks) ...
    assert "revoked_at" in card_update["payload"]
    assert card_update["payload"]["revoked_at"] is not None
    # ... scoped to the caller's own cards (cannot revoke another user's) ...
    assert ("user_id", "u-1") in card_update["filters"]
    # ... and only on cards not already revoked (the audit timestamp of an earlier revoke is
    # never rewritten): the `.is_("revoked_at", "null")` filter is recorded.
    assert ("revoked_at", "null") in card_update["filters"]


# ---------------------------------------------------------------------------
# account_status (the computed 90-day recovery window; no write)
# ---------------------------------------------------------------------------


def test_account_status_active_account_reports_not_deleted(monkeypatch):
    anon = FakeClient({("user_profile", "select"): FakeResponse({"deleted_at": None})})
    captured = _patch_anon(monkeypatch, anon)

    status = svc.account_status(USER)

    assert status == {
        "deleted": False,
        "deleted_at": None,
        "hard_delete_due_at": None,
        "reactivatable": False,
    }
    # Read under the caller's token, scoped to the caller's own row.
    assert captured["anon_token"] == "tok-abc"
    assert ("id", "u-1") in anon.calls[0]["filters"]


def test_account_status_fails_open_to_not_deleted_when_read_raises(monkeypatch):
    # Same fail-open as is_account_deleted: GET /me/account-status must not 500 when the
    # deleted_at read errors. It reports the account as active (not deleted, not reactivatable)
    # rather than propagating the error.
    anon = _RaisingClient({})
    _patch_anon(monkeypatch, anon)

    status = svc.account_status(USER)

    assert status == {
        "deleted": False,
        "deleted_at": None,
        "hard_delete_due_at": None,
        "reactivatable": False,
    }


def test_account_status_within_window_is_reactivatable_and_computes_due_at(monkeypatch):
    deleted_at = datetime.now(timezone.utc) - timedelta(days=10)
    anon = FakeClient(
        {("user_profile", "select"): FakeResponse({"deleted_at": _iso(deleted_at)})}
    )
    _patch_anon(monkeypatch, anon)

    status = svc.account_status(USER)

    assert status["deleted"] is True
    assert status["reactivatable"] is True
    # hard_delete_due_at is COMPUTED as deleted_at + 90 days, never stored.
    expected_due = (deleted_at + timedelta(days=svc.RECOVERY_WINDOW_DAYS)).isoformat()
    assert status["hard_delete_due_at"] == expected_due
    assert status["deleted_at"] == deleted_at.isoformat()


def test_account_status_past_window_is_deleted_but_not_reactivatable(monkeypatch):
    # 100 days > the 90-day window: still deleted, but past recovery (data due for the purge).
    deleted_at = datetime.now(timezone.utc) - timedelta(days=100)
    anon = FakeClient(
        {("user_profile", "select"): FakeResponse({"deleted_at": _iso(deleted_at)})}
    )
    _patch_anon(monkeypatch, anon)

    status = svc.account_status(USER)

    assert status["deleted"] is True
    assert status["reactivatable"] is False
    assert status["hard_delete_due_at"] == (
        deleted_at + timedelta(days=svc.RECOVERY_WINDOW_DAYS)
    ).isoformat()


# ---------------------------------------------------------------------------
# reactivate_account (clears deleted_at inside the window; refuses past it)
# ---------------------------------------------------------------------------


def test_reactivate_within_window_clears_deleted_at_on_callers_own_row(monkeypatch):
    anon = FakeClient(
        {
            ("user_profile", "select"): FakeResponse({"deleted_at": _ago(5)}),
            ("user_profile", "update"): FakeResponse([{"id": "u-1", "deleted_at": None}]),
        }
    )
    captured = _patch_anon(monkeypatch, anon)

    result = svc.reactivate_account(USER)

    assert result == {"reactivated": True}
    assert captured["anon_token"] == "tok-abc"
    update_call = next(
        c for c in anon.calls if c["table"] == "user_profile" and c["op"] == "update"
    )
    # It CLEARS deleted_at (sets it null) on the caller's own row (cannot reactivate another).
    assert update_call["payload"] == {"deleted_at": None}
    assert ("id", "u-1") in update_call["filters"]


def test_reactivate_past_window_raises_and_does_not_write(monkeypatch):
    # 120 days > the 90-day window: reactivation is refused (AccountPurgedError -> 410) and
    # deleted_at is left untouched (no update call), so the account stays purge-eligible.
    anon = FakeClient({("user_profile", "select"): FakeResponse({"deleted_at": _ago(120)})})
    _patch_anon(monkeypatch, anon)

    with pytest.raises(svc.AccountPurgedError):
        svc.reactivate_account(USER)

    assert not any(c["op"] == "update" for c in anon.calls)


def test_reactivate_on_active_account_is_idempotent_success_no_write(monkeypatch):
    # Not deleted: idempotent success, no write (the benign already-active race).
    anon = FakeClient({("user_profile", "select"): FakeResponse({"deleted_at": None})})
    _patch_anon(monkeypatch, anon)

    result = svc.reactivate_account(USER)

    assert result == {"reactivated": True}
    assert not any(c["op"] == "update" for c in anon.calls)
