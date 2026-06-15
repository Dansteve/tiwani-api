"""No-DB tests for the Village Hub endpoints + the village service.

Two layers, both off a live Supabase (blocked in the sandbox; mocked), mirroring
tests/test_cards_routes.py:

  - ROUTE wiring (TestClient against main.app): the current-user dependency is overridden
    for the authed cases (left real for the 401 case) and the service is monkeypatched, so
    the parse -> call-service -> serialize path and the auth / 403 / 404 / 409 / 201
    contract are tested. It pins the NeedActionResult + NeedSummary + NeedDetail shapes the
    app consumes, and that EVERY Hub route requires auth.

  - SERVICE (the real service + a fake Supabase client whose .rpc can raise APIError):
    get_anon_client is patched so the REAL service runs over scripted RPC responses /
    errors. This pins the Postgres-SQLSTATE -> typed-error mapping (42501 -> not-owner /
    not-member / not-claimer; P0001 -> conflict / consent-required; P0002 -> not-found),
    the governed copy-key on each action result, and the per-claim minimum-visibility shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest
from postgrest.exceptions import APIError

import app.routes.village as village_routes
import app.services.village as village_service
from app.auth import AuthedUser, get_current_user
from app.models.village import (
    ConsentRecorded,
    NeedActionResult,
    NeedDetail,
    NeedStatus,
    NeedSummary,
    NeedSummaryPage,
    RosterResponse,
)
from tests.fakes_supabase import FakeResponse

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")
RECIP = "recip-1"
NEED = "need-1"


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ===========================================================================
# A fake client whose .rpc(fn) returns a scripted value OR raises a scripted APIError,
# and whose .table(...).execute() returns a scripted child_profile name row.
# ===========================================================================


def _api_error(code: str, message: str) -> APIError:
    return APIError({"code": code, "message": message, "details": "", "hint": ""})


class ScriptedRpc:
    def __init__(self, fn: str, params: Any, scripts: Dict[str, Any], log: List[Tuple[str, Any]]):
        self._fn = fn
        self._params = params
        self._scripts = scripts
        self._log = log

    def execute(self):
        self._log.append((self._fn, self._params))
        if self._fn not in self._scripts:
            raise AssertionError(f"no scripted rpc response for {self._fn}")
        scripted = self._scripts[self._fn]
        # An APIError script raises (the error-mapping tests). Otherwise the scripted value
        # IS the .data the RPC returns: a list of row dicts for a `returns table` RPC, or a
        # scalar (an id) for a scalar RPC. It is returned as-is on every call (no popping),
        # so a follow-up read in the same flow sees the same data.
        if isinstance(scripted, APIError):
            raise scripted
        return FakeResponse(scripted)


class ScriptedNameQuery:
    """A minimal child_profile.select('name')...execute() returning the scripted name row."""

    def __init__(self, name_row: Optional[Dict[str, Any]]):
        self._row = name_row

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return FakeResponse(self._row)


class VillageFakeClient:
    """A fake Supabase client for the village service: scripted RPCs + a name row + roster."""

    def __init__(self, *, rpc_scripts: Dict[str, Any], name_row=None, roster_rows=None):
        self.rpc_scripts = rpc_scripts
        self.name_row = name_row if name_row is not None else {"name": "Sam Taylor"}
        self.roster_rows = roster_rows
        self.rpc_log: List[Tuple[str, Any]] = []

    def rpc(self, fn: str, params: Any = None):
        return ScriptedRpc(fn, params, self.rpc_scripts, self.rpc_log)

    def table(self, name: str):
        if name == "recipient_membership":
            return ScriptedNameQuery(self.roster_rows)
        return ScriptedNameQuery(self.name_row)


def _patch_client(monkeypatch, fake: VillageFakeClient):
    monkeypatch.setattr(village_service, "get_anon_client", lambda token=None: fake)


# ===========================================================================
# every route requires auth
# ===========================================================================


def test_every_village_route_requires_authentication(client):
    # No dependency override: the real auth dependency rejects each with 401. Every Hub
    # route is behind auth (there is no unauthenticated surface).
    posts = [
        ("/api/v1/village/consent", {"recipient_id": RECIP}),
        ("/api/v1/village/needs", {"recipient_id": RECIP, "title": "x"}),
        (f"/api/v1/village/needs/{NEED}/claim", None),
        (f"/api/v1/village/needs/{NEED}/confirm", None),
        (f"/api/v1/village/needs/{NEED}/done", None),
        (f"/api/v1/village/needs/{NEED}/drop", None),
        (f"/api/v1/village/needs/{NEED}/cancel", None),
    ]
    for path, body in posts:
        assert client.post(path, json=body).status_code == 401, path
    gets = [
        f"/api/v1/village/needs?recipient_id={RECIP}",
        f"/api/v1/village/needs/{NEED}",
        f"/api/v1/village/roster?recipient_id={RECIP}",
    ]
    for path in gets:
        assert client.get(path).status_code == 401, path


# ===========================================================================
# SERVICE: the SQLSTATE -> typed-error mapping (the core safety behaviour)
# ===========================================================================


def test_consent_required_maps_to_a_distinct_error(monkeypatch):
    err = _api_error("P0001", "village consent not recorded for this recipient")
    fake = VillageFakeClient(rpc_scripts={"create_village_need": err})
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.ConsentRequiredError):
        village_service.create_need(
            AUTHED, recipient_id=RECIP, title="School run", detail=None,
            location_text=None, area_label=None, contact_name=None, contact_phone=None,
            starts_at=None, ends_at=None,
        )


def test_not_owner_maps_from_42501_owner_message(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={"create_village_need": _api_error("42501", "not the owner of this recipient")},
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.NotOwnerError):
        village_service.create_need(
            AUTHED, recipient_id=RECIP, title="x", detail=None, location_text=None,
            area_label=None, contact_name=None, contact_phone=None, starts_at=None, ends_at=None,
        )


def test_not_member_maps_from_42501_member_message(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={"claim_village_need": _api_error("42501", "not a member of this recipient")},
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.NotMemberError):
        village_service.claim_need(AUTHED, need_id=NEED)


def test_not_claimer_maps_from_42501_claimer_message(monkeypatch):
    err = _api_error("42501", "only the claimer can mark this need done")
    fake = VillageFakeClient(rpc_scripts={"complete_village_need": err})
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.NotClaimerError):
        village_service.complete_need(AUTHED, need_id=NEED)


def test_conflict_maps_from_p0001_state_message(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={"claim_village_need": _api_error("P0001", "need is no longer open to claim")},
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.NeedConflictError):
        village_service.claim_need(AUTHED, need_id=NEED)


def test_not_found_maps_from_p0002(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={"confirm_village_need": _api_error("P0002", "need not found")},
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.NeedNotFoundError):
        village_service.confirm_need(AUTHED, need_id=NEED)


def test_unexpected_api_error_is_not_swallowed(monkeypatch):
    # A genuine fault (an unknown SQLSTATE) is re-raised, never turned into a friendly 4xx.
    fake = VillageFakeClient(
        rpc_scripts={"claim_village_need": _api_error("40001", "serialization failure")},
    )
    _patch_client(monkeypatch, fake)
    with pytest.raises(APIError):
        village_service.claim_need(AUTHED, need_id=NEED)


# ===========================================================================
# SERVICE: the action result carries the governed copy-key + the authoritative status
# ===========================================================================


def test_claim_returns_the_warm_copy_key_and_status(monkeypatch):
    # claim succeeds; the service reads the need back (the detail RPC) to report status+name.
    fake = VillageFakeClient(
        rpc_scripts={
            "claim_village_need": NEED,
            "get_village_need_detail": [
                {
                    "id": NEED, "status": "claimed", "title": "School run", "detail": None,
                    "area_label": "North Leeds", "location_text": "123 School Lane",
                    "contact_name": "Ada", "contact_phone": "07000",
                    "starts_at": None, "ends_at": None,
                    "recipient_first_name": "Sam", "claimed_by_me": True, "is_claimed": True,
                }
            ],
        },
    )
    _patch_client(monkeypatch, fake)
    result = village_service.claim_need(AUTHED, need_id=NEED)
    assert isinstance(result, NeedActionResult)
    assert result.status == NeedStatus.CLAIMED
    assert result.copy_key == "need.claim_confirmation"
    # The rendered message is warm and names the recipient, and contains no prohibited word.
    assert "Sam" not in result.message or "offer" in result.message.lower()
    assert result.message  # non-empty governed copy


def test_post_returns_open_and_posted_copy_key(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={"create_village_need": NEED},
        name_row={"name": "Sam Taylor"},
    )
    _patch_client(monkeypatch, fake)
    result = village_service.create_need(
        AUTHED, recipient_id=RECIP, title="School run", detail="Pick up at 3pm",
        location_text="123 School Lane", area_label="North Leeds",
        contact_name="Ada", contact_phone="07000", starts_at=None, ends_at=None,
    )
    assert result.status == NeedStatus.OPEN
    assert result.copy_key == "need.posted_confirmation"


def test_drop_returns_open_and_drop_copy_key(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={
            "drop_village_need": NEED,
            "get_village_need_detail": [
                {
                    "id": NEED, "status": "open", "title": "School run", "detail": None,
                    "area_label": "North Leeds", "location_text": None,
                    "contact_name": None, "contact_phone": None,
                    "starts_at": None, "ends_at": None,
                    "recipient_first_name": "Sam", "claimed_by_me": False, "is_claimed": False,
                }
            ],
        },
    )
    _patch_client(monkeypatch, fake)
    result = village_service.drop_need(AUTHED, need_id=NEED)
    assert result.status == NeedStatus.OPEN
    assert result.copy_key == "need.drop_confirmation"


# ===========================================================================
# SERVICE: minimum-visibility list + per-claim detail shaping
# ===========================================================================


def test_list_returns_summaries_without_exact_location_or_contact(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={
            "list_village_needs": [
                {
                    "id": NEED, "status": "open", "title": "School run", "detail": "3pm pickup",
                    "area_label": "North Leeds", "starts_at": None, "ends_at": None,
                    "recipient_first_name": "Sam", "claimed_by_me": False, "is_claimed": False,
                }
            ]
        },
    )
    _patch_client(monkeypatch, fake)
    page = village_service.list_needs(AUTHED, recipient_id=RECIP)
    assert isinstance(page, NeedSummaryPage)
    # One need is under the page size, so there is no next page.
    assert page.next_cursor is None
    assert len(page.needs) == 1
    summary = page.needs[0]
    assert isinstance(summary, NeedSummary)
    assert summary.area_label == "North Leeds"
    # NeedSummary has no field for the exact location / contact at all (minimum visibility).
    assert not hasattr(summary, "location_text")
    assert not hasattr(summary, "contact_name")


def _need_rows(*ids: str):
    """A list of minimal open-need RPC rows in the given (board) order."""
    return [
        {
            "id": nid, "status": "open", "title": f"Need {nid}", "detail": None,
            "area_label": "North Leeds", "starts_at": None, "ends_at": None,
            "recipient_first_name": "Sam", "claimed_by_me": False, "is_claimed": False,
        }
        for nid in ids
    ]


def test_list_needs_pages_with_a_keyset_cursor(monkeypatch):
    # The RPC returns the full live board (three needs, in board order); a limit of 2 yields
    # the first 2 plus a next_cursor of the second need's id (the keyset for ?after).
    fake = VillageFakeClient(rpc_scripts={"list_village_needs": _need_rows("n1", "n2", "n3")})
    _patch_client(monkeypatch, fake)

    page = village_service.list_needs(AUTHED, recipient_id=RECIP, limit=2)

    assert [n.id for n in page.needs] == ["n1", "n2"]
    assert page.next_cursor == "n2"


def test_list_needs_after_cursor_returns_the_next_page(monkeypatch):
    # ?after=n2 skips up to and including n2 in the board order, so the next page is n3, and
    # being the last (under the limit) it carries a null cursor.
    fake = VillageFakeClient(rpc_scripts={"list_village_needs": _need_rows("n1", "n2", "n3")})
    _patch_client(monkeypatch, fake)

    page = village_service.list_needs(AUTHED, recipient_id=RECIP, limit=2, after="n2")

    assert [n.id for n in page.needs] == ["n3"]
    assert page.next_cursor is None


def test_list_needs_unknown_cursor_restarts_from_the_top(monkeypatch):
    # A cursor whose need has left the live board (claimed-and-done / cancelled between pages)
    # is not found, so the page safely restarts from the top of the now-shorter board rather
    # than erroring.
    fake = VillageFakeClient(rpc_scripts={"list_village_needs": _need_rows("n1", "n2")})
    _patch_client(monkeypatch, fake)

    page = village_service.list_needs(AUTHED, recipient_id=RECIP, limit=5, after="gone")

    assert [n.id for n in page.needs] == ["n1", "n2"]
    assert page.next_cursor is None


def test_detail_carries_logistics_when_the_rpc_returns_them(monkeypatch):
    # The RPC decides whether to populate the exact logistics (claimer/owner) or null them;
    # the service simply carries what the RPC returned.
    fake = VillageFakeClient(
        rpc_scripts={
            "get_village_need_detail": [
                {
                    "id": NEED, "status": "claimed", "title": "School run", "detail": None,
                    "area_label": "North Leeds", "location_text": "123 School Lane",
                    "contact_name": "Ada", "contact_phone": "07000",
                    "starts_at": None, "ends_at": None,
                    "recipient_first_name": "Sam", "claimed_by_me": True, "is_claimed": True,
                }
            ]
        },
    )
    _patch_client(monkeypatch, fake)
    detail = village_service.get_need_detail(AUTHED, need_id=NEED)
    assert isinstance(detail, NeedDetail)
    assert detail.location_text == "123 School Lane"
    assert detail.contact_name == "Ada"


def test_detail_nulls_logistics_when_the_rpc_nulls_them(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={
            "get_village_need_detail": [
                {
                    "id": NEED, "status": "open", "title": "School run", "detail": None,
                    "area_label": "North Leeds", "location_text": None,
                    "contact_name": None, "contact_phone": None,
                    "starts_at": None, "ends_at": None,
                    "recipient_first_name": "Sam", "claimed_by_me": False, "is_claimed": False,
                }
            ]
        },
    )
    _patch_client(monkeypatch, fake)
    detail = village_service.get_need_detail(AUTHED, need_id=NEED)
    assert detail.location_text is None
    assert detail.contact_name is None


def test_detail_not_found_raises(monkeypatch):
    fake = VillageFakeClient(rpc_scripts={"get_village_need_detail": []})
    _patch_client(monkeypatch, fake)
    with pytest.raises(village_service.NeedNotFoundError):
        village_service.get_need_detail(AUTHED, need_id=NEED)


# ===========================================================================
# SERVICE: consent records the governed text; roster shape
# ===========================================================================


def test_record_consent_stores_the_governed_text(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={"record_village_consent": "consent-id-1"},
        name_row={"name": "Sam Taylor"},
    )
    _patch_client(monkeypatch, fake)
    result = village_service.record_consent(AUTHED, recipient_id=RECIP)
    assert isinstance(result, ConsentRecorded)
    # The stored text is the governed consent copy with the first name resolved.
    assert "Sam" in result.consent_text
    assert "authority" in result.consent_text.lower()
    # And the RPC was called with that exact text (the api supplies it, not the client).
    fn, params = fake.rpc_log[0]
    assert fn == "record_village_consent"
    assert params["p_consent_text"] == result.consent_text


def test_roster_returns_active_members_with_is_me(monkeypatch):
    fake = VillageFakeClient(
        rpc_scripts={},
        name_row={"name": "Sam Taylor"},
        roster_rows=[
            {"user_id": "u-1", "role": "owner", "granted_at": None, "revoked_at": None},
            {"user_id": "u-2", "role": "viewer", "granted_at": None, "revoked_at": None},
        ],
    )
    _patch_client(monkeypatch, fake)
    roster = village_service.get_roster(AUTHED, recipient_id=RECIP)
    assert isinstance(roster, RosterResponse)
    assert roster.recipient_first_name == "Sam"
    assert {m.user_id for m in roster.members} == {"u-1", "u-2"}
    me = next(m for m in roster.members if m.user_id == "u-1")
    assert me.is_me is True


# ===========================================================================
# ROUTE: the typed errors map to the right HTTP codes
# ===========================================================================


def test_post_need_consent_required_is_409(authed, monkeypatch):
    def boom(*a, **k):
        raise village_service.ConsentRequiredError("village consent not recorded")
    monkeypatch.setattr(village_routes.village_service, "create_need", boom)
    r = authed.post("/api/v1/village/needs", json={"recipient_id": RECIP, "title": "School run"})
    assert r.status_code == 409
    # N3: the route returns GOVERNED, guarded copy, never the raw Postgres RPC message.
    detail = r.json()["detail"]
    assert "village consent not recorded" not in detail  # the raw RPC text is never leaked
    assert detail == village_routes.render_copy("need.conflict.consent_required")


def test_post_need_not_owner_is_403(authed, monkeypatch):
    def boom(*a, **k):
        raise village_service.NotOwnerError("not the owner")
    monkeypatch.setattr(village_routes.village_service, "create_need", boom)
    r = authed.post("/api/v1/village/needs", json={"recipient_id": RECIP, "title": "School run"})
    assert r.status_code == 403
    # N3 follow-up: the 403 detail is GOVERNED, guarded copy, never the raw service text
    # and never the internal role label ("owner").
    detail = r.json()["detail"]
    assert "not the owner" not in detail
    assert "owner" not in detail.lower()
    assert detail == village_routes.render_copy("error.family_only")


def test_claim_conflict_is_409(authed, monkeypatch):
    def boom(*a, **k):
        raise village_service.NeedConflictError("need is no longer open to claim")
    monkeypatch.setattr(village_routes.village_service, "claim_need", boom)
    r = authed.post(f"/api/v1/village/needs/{NEED}/claim")
    assert r.status_code == 409
    # N3: the route returns GOVERNED, guarded copy, never the raw Postgres RPC message.
    detail = r.json()["detail"]
    assert "no longer open to claim" not in detail  # the raw RPC text is never leaked
    assert detail == village_routes.render_copy("need.claim_taken")


def test_claim_not_member_is_403(authed, monkeypatch):
    def boom(*a, **k):
        raise village_service.NotMemberError("not a member")
    monkeypatch.setattr(village_routes.village_service, "claim_need", boom)
    r = authed.post(f"/api/v1/village/needs/{NEED}/claim")
    assert r.status_code == 403
    # N3 follow-up: GOVERNED, guarded copy for the not-in-village 403, never the raw text.
    detail = r.json()["detail"]
    assert "not a member" not in detail
    assert detail == village_routes.render_copy("error.not_in_village")


def test_done_not_claimer_is_403(authed, monkeypatch):
    def boom(*a, **k):
        raise village_service.NotClaimerError("only the claimer can mark this done")
    monkeypatch.setattr(village_routes.village_service, "complete_need", boom)
    r = authed.post(f"/api/v1/village/needs/{NEED}/done")
    assert r.status_code == 403
    # N3 follow-up: GOVERNED, guarded copy for the helper-only 403, never the raw text.
    detail = r.json()["detail"]
    assert "only the claimer" not in detail
    assert detail == village_routes.render_copy("error.helper_only")


def test_get_need_not_found_is_404(authed, monkeypatch):
    def boom(*a, **k):
        raise village_service.NeedNotFoundError("need not found")
    monkeypatch.setattr(village_routes.village_service, "get_need_detail", boom)
    r = authed.get(f"/api/v1/village/needs/{NEED}")
    assert r.status_code == 404
    # N3 follow-up: GOVERNED, guarded copy for the 404, never the raw service text.
    detail = r.json()["detail"]
    assert "need not found" not in detail.lower()
    assert detail == village_routes.render_copy("error.need_not_found")


def test_post_need_happy_path_is_201_with_copy_key(authed, monkeypatch):
    monkeypatch.setattr(
        village_routes.village_service, "create_need",
        lambda *a, **k: NeedActionResult(
            id=NEED, status=NeedStatus.OPEN, copy_key="need.posted_confirmation",
            message="Shared with the family's village.",
        ),
    )
    r = authed.post("/api/v1/village/needs", json={"recipient_id": RECIP, "title": "School run"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "open"
    assert body["copy_key"] == "need.posted_confirmation"


def test_list_needs_happy_path_serializes_summaries(authed, monkeypatch):
    monkeypatch.setattr(
        village_routes.village_service, "list_needs",
        lambda *a, **k: NeedSummaryPage(
            needs=[
                NeedSummary(
                    id=NEED, status=NeedStatus.OPEN, title="School run", detail=None,
                    area_label="North Leeds", recipient_first_name="Sam",
                    claimed_by_me=False, is_claimed=False,
                )
            ],
            next_cursor=None,
        ),
    )
    r = authed.get(f"/api/v1/village/needs?recipient_id={RECIP}")
    assert r.status_code == 200
    body = r.json()
    # The paginated NeedSummaryPage envelope: a `needs` page + a `next_cursor`.
    assert set(body.keys()) == {"needs", "next_cursor"}
    assert body["next_cursor"] is None
    assert body["needs"][0]["area_label"] == "North Leeds"
    # The summary serialization carries no exact location / contact key.
    assert "location_text" not in body["needs"][0]
    assert "contact_name" not in body["needs"][0]


def test_list_needs_passes_the_limit_and_cursor_to_the_service(authed, monkeypatch):
    captured = {}

    def _capture(user, **kwargs):
        captured.update(kwargs)
        return NeedSummaryPage(needs=[], next_cursor=None)

    monkeypatch.setattr(village_routes.village_service, "list_needs", _capture)
    r = authed.get(f"/api/v1/village/needs?recipient_id={RECIP}&limit=10&after=need-9")
    assert r.status_code == 200
    assert captured.get("limit") == 10
    assert captured.get("after") == "need-9"


def test_list_needs_rejects_a_limit_over_the_cap_422(authed):
    # The route enforces 1..NEED_LIST_MAX_LIMIT (100) via Query(le=...), so a larger ?limit
    # is a 422 before the service is reached (the cap can never be bypassed from the wire).
    r = authed.get(f"/api/v1/village/needs?recipient_id={RECIP}&limit=1000")
    assert r.status_code == 422


def test_post_need_title_is_required_422(authed):
    # An empty title fails pydantic validation (min_length=1) before the service is reached.
    r = authed.post("/api/v1/village/needs", json={"recipient_id": RECIP, "title": ""})
    assert r.status_code == 422


# ===========================================================================
# N3 follow-up: the 403/404 error copy is GOVERNED + passes the guard
# ===========================================================================


@pytest.mark.parametrize(
    "key",
    ["error.family_only", "error.helper_only", "error.not_in_village", "error.need_not_found"],
)
def test_village_error_copy_keys_render_clean_through_the_guard(key):
    # The route maps every 403/404 through render_copy(key); render() runs assert_clean
    # internally, so a prohibited word (clinical / surveillance / a role label) could never
    # be emitted. A KeyError here would mean the route names a key the copy module lacks.
    from app.engines.village import find_prohibited_words

    text = village_routes.render_copy(key)
    assert text  # non-empty governed copy
    assert find_prohibited_words(text) == []
