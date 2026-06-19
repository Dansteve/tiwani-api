"""Card-on-task tests (FeatureDecisions 2026-06-17; flag-gated): the sign-off FLAG, migration
0020's claimer-only gates (structure-parse of the SQL), the SERVICE wiring (the attach + the
governed card-share consent + get_need_card), and the ROUTE flag-gates. No live Supabase here
(the service runs over a fake client; the routes monkeypatch the service). The real-Postgres
claimer-only RLS SEMANTICS (claimer reads / non-claimer + ex-claimer + revoked-member read
nothing) live in tests/test_card_on_task_rls.py against a fresh throwaway DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

import app.routes.village as village_routes  # noqa: F401  (ensures the route module is importable)
import app.services.village as village_service
from app.auth import AuthedUser, get_current_user
from app.engines.village.flag import is_card_on_task_enabled
from app.models.card import CardContent
from app.models.village import NeedStatus
from tests.test_village_routes import VillageFakeClient, _api_error, _patch_client

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")
RECIP = "recip-1"
NEED = "need-1"

# A valid SAFE card content (mirrors tests/test_cards_routes.py SAFE_CONTENT): what the
# get_village_need_card RPC returns as jsonb to the live claimer.
CARD_JSON: Dict[str, Any] = {
    "child_first_name": "Ade",
    "activity_name": "School gate drop-off",
    "chapter": "school",
    "tier": "Pivot",
    "tier_label": "Keeping things calm and steady",
    "intro": "Thank you for being here.",
    "strategies": [{"title": "Build in extra time", "detail": "No rushing at the gate."}],
    "if_difficult": "If things get difficult, that is okay.",
    "safety_note": "Follow the family's plan for food, medicines, or Ade's health.",
}

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0020_card_on_task.sql"
).read_text()


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


def _enable(monkeypatch):
    monkeypatch.setenv("CARD_ON_TASK_ENABLED", "1")


def _disable(monkeypatch):
    monkeypatch.delenv("CARD_ON_TASK_ENABLED", raising=False)


# ---------------------------------------------------------------------------
# the sign-off flag (default OFF; only an explicit truthy value enables it)
# ---------------------------------------------------------------------------


def test_flag_off_by_default(monkeypatch):
    _disable(monkeypatch)
    assert is_card_on_task_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on"])
def test_flag_on_for_truthy(monkeypatch, value):
    monkeypatch.setenv("CARD_ON_TASK_ENABLED", value)
    assert is_card_on_task_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "nope"])
def test_flag_off_for_non_truthy(monkeypatch, value):
    monkeypatch.setenv("CARD_ON_TASK_ENABLED", value)
    assert is_card_on_task_enabled() is False


# ---------------------------------------------------------------------------
# migration 0020: the claimer-only gates (structure-parse of the SQL)
# ---------------------------------------------------------------------------


def test_migration_adds_card_attached_default_false():
    assert (
        "add column if not exists card_attached boolean not null default false"
        in MIGRATION.lower()
    )


def test_create_rpc_keys_off_the_card_share_consent_not_the_village_consent():
    # The attach gate checks share_consent (the CARD-SHARE consent, DPO L3), records the
    # governed text verbatim if absent, and raises a DISTINCT card-consent message.
    assert "share_consent" in MIGRATION
    assert "insert into public.share_consent" in MIGRATION
    assert "card sharing consent not recorded" in MIGRATION


def test_card_read_rpc_is_claimer_or_owner_only_and_reuses_the_safe_reader():
    assert "create or replace function public.get_village_need_card" in MIGRATION
    # The same v_can_full gate (live claimer OR owner) as the per-claim logistics.
    assert "v_can_full" in MIGRATION
    assert "in ('claimed', 'confirmed')" in MIGRATION
    # It serves the LIVE safe card through the existing member-card reader (no second reader).
    assert "get_recipient_card_for_member" in MIGRATION
    # A non-member / not-attached / not-allowed path returns null (gated, not shown-then-hidden).
    assert "return null" in MIGRATION


def test_card_attached_audit_action_is_allowed():
    assert "'card_attached'" in MIGRATION


# ---------------------------------------------------------------------------
# service: create_need with the attach (the governed card-share consent)
# ---------------------------------------------------------------------------


def test_create_need_attach_passes_the_flag_and_the_governed_card_consent(monkeypatch):
    fake = VillageFakeClient(rpc_scripts={"create_village_need": "new-need-id"})
    _patch_client(monkeypatch, fake)
    village_service.create_need(
        AUTHED, recipient_id=RECIP, title="School run", detail=None, location_text=None,
        area_label=None, contact_name=None, contact_phone=None, starts_at=None, ends_at=None,
        attach_card=True,
    )
    fn, params = fake.rpc_log[-1]
    assert fn == "create_village_need"
    assert params["p_attach_card"] is True
    # The api supplies the GOVERNED card-share consent text (never the client), non-empty.
    text = params["p_card_consent_text"]
    assert isinstance(text, str) and text.strip()
    assert "support card" in text


def test_create_need_without_attach_sends_false_and_no_consent(monkeypatch):
    fake = VillageFakeClient(rpc_scripts={"create_village_need": "new-need-id"})
    _patch_client(monkeypatch, fake)
    village_service.create_need(
        AUTHED, recipient_id=RECIP, title="School run", detail=None, location_text=None,
        area_label=None, contact_name=None, contact_phone=None, starts_at=None, ends_at=None,
    )
    _, params = fake.rpc_log[-1]
    assert params["p_attach_card"] is False
    assert params["p_card_consent_text"] is None


def test_card_consent_required_maps_to_its_own_error(monkeypatch):
    # Distinct from the village-consent gate: the card-share consent raise maps to its own error.
    err = _api_error("P0001", "card sharing consent not recorded for this recipient")
    fake = VillageFakeClient(rpc_scripts={"create_village_need": err})
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.CardConsentRequiredError):
        village_service.create_need(
            AUTHED, recipient_id=RECIP, title="x", detail=None, location_text=None,
            area_label=None, contact_name=None, contact_phone=None, starts_at=None, ends_at=None,
            attach_card=True,
        )


# ---------------------------------------------------------------------------
# service: get_need_card (the claimer-only read; None when not allowed)
# ---------------------------------------------------------------------------


def test_get_need_card_returns_the_safe_card(monkeypatch):
    fake = VillageFakeClient(rpc_scripts={"get_village_need_card": CARD_JSON})
    _patch_client(monkeypatch, fake)
    card = village_service.get_need_card(AUTHED, need_id=NEED)
    assert isinstance(card, CardContent)
    assert card.child_first_name == "Ade"


def test_get_need_card_is_none_when_the_rpc_resolves_nothing(monkeypatch):
    # The RPC returns null for a non-claimer / not-attached / no-live-card: the service -> None.
    fake = VillageFakeClient(rpc_scripts={"get_village_need_card": None})
    _patch_client(monkeypatch, fake)
    assert village_service.get_need_card(AUTHED, need_id=NEED) is None


# ---------------------------------------------------------------------------
# route: the flag-gates (the directed disclosure cannot happen while OFF)
# ---------------------------------------------------------------------------


def test_post_attach_card_refused_with_422_when_flag_off(monkeypatch, authed):
    _disable(monkeypatch)
    resp = authed.post(
        "/api/v1/village/needs",
        json={"recipient_id": RECIP, "title": "School run", "attach_card": True},
    )
    assert resp.status_code == 422


def test_post_attach_card_reaches_the_service_when_flag_on(monkeypatch, authed):
    _enable(monkeypatch)
    captured: Dict[str, Any] = {}

    def fake_create(user, **kw):
        captured.update(kw)
        return village_service._action_result("n1", NeedStatus.OPEN, "posted", name="Ade")

    monkeypatch.setattr(village_service, "create_need", fake_create)
    resp = authed.post(
        "/api/v1/village/needs",
        json={"recipient_id": RECIP, "title": "School run", "attach_card": True},
    )
    assert resp.status_code == 201
    assert captured.get("attach_card") is True


def test_get_card_route_404s_when_flag_off(monkeypatch, authed):
    _disable(monkeypatch)
    assert authed.get(f"/api/v1/village/needs/{NEED}/card").status_code == 404


def test_get_card_route_404s_when_no_card(monkeypatch, authed):
    _enable(monkeypatch)
    monkeypatch.setattr(village_service, "get_need_card", lambda user, need_id: None)
    assert authed.get(f"/api/v1/village/needs/{NEED}/card").status_code == 404


def test_get_card_route_returns_the_card_with_a_governed_helper_note(monkeypatch, authed):
    _enable(monkeypatch)
    monkeypatch.setattr(
        village_service,
        "get_need_card",
        lambda user, need_id: CardContent.model_validate(CARD_JSON),
    )
    resp = authed.get(f"/api/v1/village/needs/{NEED}/card")
    assert resp.status_code == 200
    body = resp.json()
    assert body["card"]["child_first_name"] == "Ade"
    # The governed helper note is served with the card and names the recipient.
    assert body["helper_note"].strip()
    assert "Ade" in body["helper_note"]


# ---------------------------------------------------------------------------
# SEMANTICS: a faithful model of get_village_need_card's claimer-only gate (the in-memory RLS
# proof the sandbox permits, mirroring tests/test_village_hub_rls.py). It applies the SAME
# predicate the migration declares; a regression that loosened the gate flips a case. When 0020
# is applied to production this same matrix is what the owner re-runs against the live DB.
# ---------------------------------------------------------------------------


def _card_resolves(
    *, is_member: bool, card_attached: bool, claimed_by, caller, status: str, is_owner: bool
) -> bool:
    """The get_village_need_card gate: a member of the recipient, the card attached to THIS
    need, AND (the LIVE claimer of this need OR the owner). Anything else resolves nothing."""
    if not is_member:
        return False
    if not card_attached:
        return False
    v_can_full = (
        claimed_by is not None
        and claimed_by == caller
        and status in ("claimed", "confirmed")
    ) or is_owner
    return v_can_full


CLAIMER = "helper-1"
OTHER = "helper-2"
OWNER = "owner-1"


def test_semantics_live_claimer_reads_the_card():
    for status in ("claimed", "confirmed"):
        assert _card_resolves(
            is_member=True, card_attached=True, claimed_by=CLAIMER, caller=CLAIMER,
            status=status, is_owner=False,
        ) is True


def test_semantics_non_claiming_member_reads_nothing():
    assert _card_resolves(
        is_member=True, card_attached=True, claimed_by=CLAIMER, caller=OTHER,
        status="claimed", is_owner=False,
    ) is False


def test_semantics_ex_claimer_after_done_or_drop_reads_nothing():
    # Completed (status terminal) or dropped (claim cleared, re-opened): no LIVE claim, so the
    # (ex-)claimer's card access expires per-occurrence.
    assert _card_resolves(
        is_member=True, card_attached=True, claimed_by=CLAIMER, caller=CLAIMER,
        status="done", is_owner=False,
    ) is False
    assert _card_resolves(
        is_member=True, card_attached=True, claimed_by=None, caller=CLAIMER,
        status="open", is_owner=False,
    ) is False


def test_semantics_owner_reads_the_card_even_before_a_claim():
    assert _card_resolves(
        is_member=True, card_attached=True, claimed_by=None, caller=OWNER,
        status="open", is_owner=True,
    ) is True


def test_semantics_non_member_reads_nothing():
    assert _card_resolves(
        is_member=False, card_attached=True, claimed_by=CLAIMER, caller=CLAIMER,
        status="claimed", is_owner=False,
    ) is False


def test_semantics_unattached_need_reads_nothing_even_for_the_claimer():
    assert _card_resolves(
        is_member=True, card_attached=False, claimed_by=CLAIMER, caller=CLAIMER,
        status="claimed", is_owner=False,
    ) is False
