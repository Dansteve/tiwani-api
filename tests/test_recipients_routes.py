"""No-DB tests for GET /api/v3/recipients + the recipients service (the switcher list).

Two layers, both off a live Supabase (blocked in the sandbox; the composed reads are faked):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is overridden for
    the authed case (left real for the 401 case) and the service is monkeypatched, so the
    parse -> call-service -> serialize path and the 401/200 contract + the ActiveRecipient
    shape the app's RecipientProvider consumes are pinned.

  - SERVICE (the real list_active_recipients over faked composed reads): profile.list_children
    and sharing.shared_with_me are monkeypatched, so the REAL union / role-tagging / dedupe /
    first-name logic runs. This pins refinement 1 (Docs/FeatureDecisions.md, "Helper Village
    ACCESS"): OWNED recipients are role=owner; recipients SHARED with the caller are
    role=viewer/editor; a member entry carries the id + the FIRST NAME ONLY + the role and
    NO profile fields (the visibility ceiling); owned come first; ids are de-duped.

The DATABASE-level ceiling (a viewer reads ZERO from child_profile/lci_snapshot/alert_record/
pulse_record even when surfaced in the switcher) is proven against a real Postgres in
tests/test_shared_child_rls.py; this file proves the api COMPOSES the list correctly.
"""

from __future__ import annotations

import pytest

import app.services.profile as profile_service
import app.services.recipients as recipients_service
import app.services.sharing as sharing_service
from app.auth import AuthedUser, get_current_user
from app.models.recipient import RecipientRole
from app.models.sharing import SharedRecipient, SharedWithMe

AUTHED = AuthedUser(id="owner-1", email="ada@example.com", access_token="tok-abc")

# child_profile rows (as list_children returns them): the OWNED side. Only id + name are read
# by the service; the rest of the row is present but deliberately NOT surfaced (the ceiling).
OWNED_ROWS = [
    {"id": "own-2", "user_id": "owner-1", "name": "Bisi Okafor", "support_level_code": "SL-LOW"},
    {"id": "own-1", "user_id": "owner-1", "name": "Ade Bello", "support_level_code": "SL-MED"},
]

# A recipient SHARED with the caller (shared_with_me returns these; first-name-only by design).
SHARED = SharedWithMe(
    recipients=[
        SharedRecipient(
            recipient_id="shared-1",
            recipient_first_name="Tunde",
            role="viewer",
            copy_key="sharing.linked.intro",
        )
    ]
)


# ===========================================================================
# ROUTE wiring (TestClient): auth + the ActiveRecipient shape.
# ===========================================================================


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


def test_recipients_requires_auth(client):
    """No bearer -> 401 (the current-user dependency is left real here)."""
    resp = client.get("/api/v3/recipients")
    assert resp.status_code == 401


def test_recipients_route_returns_role_tagged_shape(authed, monkeypatch):
    """The route serializes the service's ActiveRecipient list: {id, first_name, role} only."""
    from app.models.recipient import ActiveRecipient

    monkeypatch.setattr(
        recipients_service,
        "list_active_recipients",
        lambda user: [
            ActiveRecipient(id="own-1", first_name="Ade", role=RecipientRole.OWNER),
            ActiveRecipient(id="shared-1", first_name="Tunde", role=RecipientRole.VIEWER),
        ],
    )

    resp = authed.get("/api/v3/recipients")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {"id": "own-1", "first_name": "Ade", "role": "owner"},
        {"id": "shared-1", "first_name": "Tunde", "role": "viewer"},
    ]
    # The ceiling at the wire: a recipient entry exposes only these three keys, never a profile.
    for entry in body:
        assert set(entry.keys()) == {"id", "first_name", "role"}


# ===========================================================================
# SERVICE: the real union / role-tag / dedupe / first-name logic.
# ===========================================================================


def _patch(monkeypatch, owned, shared):
    monkeypatch.setattr(profile_service, "list_children", lambda user: owned)
    monkeypatch.setattr(sharing_service, "shared_with_me", lambda user: shared)


def test_owned_only_are_all_owner_role_first_named(monkeypatch):
    _patch(monkeypatch, OWNED_ROWS, SharedWithMe(recipients=[]))
    result = recipients_service.list_active_recipients(AUTHED)

    assert [r.id for r in result] == ["own-2", "own-1"]  # list_children order preserved
    assert all(r.role == RecipientRole.OWNER for r in result)
    # First name only, never the full name, even for the owner's own recipient.
    assert result[0].first_name == "Bisi"
    assert result[1].first_name == "Ade"


def test_shared_only_are_viewer_role(monkeypatch):
    _patch(monkeypatch, [], SHARED)
    result = recipients_service.list_active_recipients(AUTHED)

    assert len(result) == 1
    assert result[0].id == "shared-1"
    assert result[0].first_name == "Tunde"
    assert result[0].role == RecipientRole.VIEWER


def test_union_owned_first_then_shared(monkeypatch):
    """The blocker fix: a helper's SHARED recipients are surfaced alongside any OWNED ones."""
    _patch(monkeypatch, OWNED_ROWS, SHARED)
    result = recipients_service.list_active_recipients(AUTHED)

    assert [r.id for r in result] == ["own-2", "own-1", "shared-1"]
    assert [r.role for r in result] == [
        RecipientRole.OWNER,
        RecipientRole.OWNER,
        RecipientRole.VIEWER,
    ]


def test_member_entry_carries_no_profile_fields(monkeypatch):
    """The ceiling: a SHARED entry serializes to id + first_name + role ONLY (no profile)."""
    _patch(monkeypatch, [], SHARED)
    result = recipients_service.list_active_recipients(AUTHED)

    dumped = result[0].model_dump()
    assert set(dumped.keys()) == {"id", "first_name", "role"}
    assert "support_level_code" not in dumped and "name" not in dumped and "tags" not in dumped


def test_owned_membership_is_not_double_counted(monkeypatch):
    """If the same recipient appears as both owned and shared, it is surfaced once (owner wins)."""
    shared_dupe = SharedWithMe(
        recipients=[
            SharedRecipient(
                recipient_id="own-1",  # same id as an owned recipient
                recipient_first_name="Ade",
                role="viewer",
                copy_key="sharing.linked.intro",
            )
        ]
    )
    _patch(monkeypatch, OWNED_ROWS, shared_dupe)
    result = recipients_service.list_active_recipients(AUTHED)

    ids = [r.id for r in result]
    assert ids.count("own-1") == 1
    # The owned (owner) tag wins the dedupe, never demoted to viewer.
    assert next(r for r in result if r.id == "own-1").role == RecipientRole.OWNER


def test_empty_when_no_recipients_and_no_shares(monkeypatch):
    _patch(monkeypatch, [], SharedWithMe(recipients=[]))
    assert recipients_service.list_active_recipients(AUTHED) == []
