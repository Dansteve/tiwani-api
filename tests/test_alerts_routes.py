"""No-DB tests for the v3 Erosion Alert endpoints + the alerts service (section 4.9).

Two layers, both off a live Supabase (blocked in the sandbox; the task requires
mocking):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is
    overridden for the authed cases (left real for the 401 cases), and the service is
    monkeypatched, so the parse -> call-service -> serialize path and the 401/404
    contract are what is tested. It pins the AlertView shape the app mirrors
    ({chapter, level, copy, action_label, signposts}).

  - SERVICE (the real engine + governed copy, a fake Supabase client):
    get_anon_client is patched with a FakeClient so the REAL section 4.9 evaluation
    runs over scripted rows, the alert_record upsert/dismiss is recorded, and the
    dashboard alert_level is now populated. This pins the post-pulse evaluation, the
    dismissal "returns only on worsening" rule, and the dashboard wiring.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import app.routes.alerts as alerts_routes
import app.services.alerts as alerts_service
from app.auth import AuthedUser, get_current_user
from app.engines.alerts import AlertLevel
from app.models.alert import AlertView, SignpostView
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# The caller's sole care recipient. The READ paths (list/levels/dismiss) resolve it
# through profile.resolve_child_id (a child_profile read), then scope every alert query to
# this child_id. The post-pulse evaluation is passed the activity's child_id directly (no
# resolve), so its tests pass CHILD_ID positionally (Docs/FeatureDecisions.md, multi care
# recipient: every alert belongs to exactly one recipient).
CHILD_ID = "ch-1"
CHILD_ROW = {"id": CHILD_ID, "user_id": "u-1", "name": "Sam"}


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required (401)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/alerts"),
        ("post", "/api/v1/alerts/career/dismiss"),
    ],
)
def test_alert_routes_require_authentication(client, method, path):
    if method == "get":
        response = client.get(path)
    else:
        response = client.post(path)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /alerts route wiring (service monkeypatched) + the AlertView shape
# ---------------------------------------------------------------------------


SAMPLE_ALERT = AlertView(
    chapter="career",
    level=2,
    copy_text="Something to pay attention to. Your Career chapter ...",
    action_label="See suggestions",
    signposts=[SignpostView(label="Carers UK", url="https://www.carersuk.org")],
)


def test_get_alerts_returns_the_alertview_shape(authed, monkeypatch):
    monkeypatch.setattr(
        alerts_routes.alerts_service,
        "list_active_alerts",
        lambda user, child_id=None: [SAMPLE_ALERT],
    )
    response = authed.get("/api/v1/alerts")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    alert = body[0]
    # The contract the app mirrors: the wire field is `copy` (aliased), not copy_text.
    assert set(alert.keys()) == {"chapter", "level", "copy", "action_label", "signposts"}
    assert alert["chapter"] == "career"
    assert alert["level"] == 2
    assert alert["action_label"] == "See suggestions"
    assert alert["signposts"][0]["label"] == "Carers UK"


def test_dismiss_unknown_chapter_alert_is_404(authed, monkeypatch):
    def _raise(user, chapter, child_id=None):
        raise alerts_service.AlertNotFoundError("none")

    monkeypatch.setattr(alerts_routes.alerts_service, "dismiss_alert", _raise)
    response = authed.post("/api/v1/alerts/career/dismiss")
    assert response.status_code == 404


def test_dismiss_rejects_an_unknown_chapter_code_422(authed):
    # The path param is the Chapter enum, so a bogus code is a 422 from validation.
    response = authed.post("/api/v1/alerts/not-a-chapter/dismiss")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# SERVICE: list_active_alerts renders the governed copy from stored rows
# ---------------------------------------------------------------------------


def test_list_active_alerts_renders_governed_copy(monkeypatch):
    rows = [
        {
            "chapter": "school",
            "level": 1,
            "trigger_condition": "l1_counts_30d",
            "dismissed": False,
            "dismissed_level": None,
        },
        {
            "chapter": "career",
            "level": 3,
            "trigger_condition": "l3_lci_below_30",
            "dismissed": False,
            "dismissed_level": None,
        },
    ]
    # list_active_alerts resolves the sole recipient first (profile layer), then reads
    # only that recipient's alerts. Serve the child read from the same fake.
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([CHILD_ROW]),
            ("alert_record", "select"): FakeResponse(rows),
        }
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    alerts = {a.chapter: a for a in alerts_service.list_active_alerts(AUTHED)}
    # School L1 carries the verbatim L1 prompt + CTA; Career L3 carries the L3 ones.
    assert alerts["school"].level == 1
    assert "under some pressure recently" in alerts["school"].copy_text
    assert alerts["school"].action_label == "Review support options"
    assert alerts["career"].level == 3
    assert "continuity needs attention" in alerts["career"].copy_text
    assert alerts["career"].action_label == "Find support"
    # The alert read was scoped to the resolved recipient (the isolation rule).
    alert_select = next(
        c for c in fake.calls if c["table"] == "alert_record" and c["op"] == "select"
    )
    assert ("child_id", CHILD_ID) in alert_select["filters"]
    # BOUNDED (the every-list-is-capped rule): at most one active alert per chapter (<= 6),
    # but the read still carries a safety `.limit(...)` as the runaway-read backstop.
    from app.services.pagination import MAX_BOUNDED_ROWS

    assert alert_select["limit"] == MAX_BOUNDED_ROWS


def test_active_levels_by_chapter_feeds_the_dashboard(monkeypatch):
    # The dashboard resolves the recipient once and passes the child_id in; this helper
    # does not resolve, it reads exactly the given recipient's active alerts.
    rows = [
        {"chapter": "travel", "level": 2, "dismissed": False, "dismissed_level": None},
    ]
    fake = FakeClient({("alert_record", "select"): FakeResponse(rows)})
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)

    levels = alerts_service.active_levels_by_chapter(AUTHED, CHILD_ID)
    assert levels == {"travel": 2}
    # Scoped to the passed recipient.
    assert ("child_id", CHILD_ID) in next(
        c for c in fake.calls if c["table"] == "alert_record" and c["op"] == "select"
    )["filters"]


def test_active_levels_by_chapter_is_empty_without_a_recipient(monkeypatch):
    # No resolved recipient (child_id None): the helper reads nothing (no alert query).
    fake = FakeClient({("alert_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    assert alerts_service.active_levels_by_chapter(AUTHED, None) == {}
    assert not any(c["table"] == "alert_record" for c in fake.calls)


# ---------------------------------------------------------------------------
# SERVICE: the post-pulse evaluation upserts the alert_record
# ---------------------------------------------------------------------------


def _history_fake(*, activities, pulses, snapshots, alert_select, lci_pulses=None):
    """A FakeClient scripting the chapter-history reads the evaluation makes.

    activities -> activity_record select; pulses -> the alerts service's own
    pulse_record select; lci_pulses -> the LCI fold's pulse_record select (defaults to
    `pulses` shaped for the LCI). snapshots -> lci_snapshot select; alert_select -> the
    existing alert_record select. The alert_record insert/update/delete are accepted.
    Because both the alerts service AND the LCI service read pulse_record through the
    SAME fake here, the pulse_record select is scripted as an ordered list: first the
    alerts read, then the LCI read.
    """
    lci_rows = lci_pulses if lci_pulses is not None else pulses
    return FakeClient(
        {
            ("activity_record", "select"): FakeResponse(activities),
            ("pulse_record", "select"): [FakeResponse(pulses), FakeResponse(lci_rows)],
            ("lci_snapshot", "select"): FakeResponse(snapshots),
            ("alert_record", "select"): FakeResponse(alert_select),
            ("alert_record", "insert"): FakeResponse([{"id": "al-1"}]),
            ("alert_record", "update"): FakeResponse([{"id": "al-1"}]),
            ("alert_record", "delete"): FakeResponse([]),
        }
    )


def test_post_pulse_evaluation_inserts_an_l3_alert(monkeypatch):
    # Three Pivot activities + three Difficult pulses in 14 days -> L3 (counts branch),
    # no existing alert -> a fresh active L3 row is inserted.
    activities = [{"tier": "Pivot", "created_at": _iso(7)} for _ in range(3)]
    pulses = [{"outcome_code": "difficult", "created_at": _iso(7)} for _ in range(3)]
    # The LCI fold sees the same three Difficult pulses on Pivot activities: from 50,
    # +2 each = 56 (healthy), so the L3 here is purely the counts branch.
    lci_rows = [
        {
            "chapter": "career",
            "outcome_code": "difficult",
            "tier_recommended": "Pivot",
            "created_at": _iso(7),
        }
        for _ in range(3)
    ]
    fake = _history_fake(
        activities=activities,
        pulses=pulses,
        snapshots=[],
        alert_select=[],
        lci_pulses=lci_rows,
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    level = alerts_service.evaluate_chapter_alert(AUTHED, "career", CHILD_ID, now=NOW)
    assert level is AlertLevel.L3

    inserts = [c for c in fake.calls if c["op"] == "insert" and c["table"] == "alert_record"]
    assert len(inserts) == 1
    payload = inserts[0]["payload"]
    assert payload["user_id"] == "u-1"
    assert payload["child_id"] == CHILD_ID  # the alert is the recipient's, per migration 0010
    assert payload["chapter"] == "career"
    assert payload["level"] == 3
    assert payload["trigger_condition"] == "l3_counts_14d"
    assert payload["dismissed"] is False
    # Isolation: every history read and the alert write was scoped to this ONE recipient.
    for call in fake.calls:
        if call["table"] in ("activity_record", "pulse_record", "lci_snapshot", "alert_record"):
            seen = {v for (col, v) in call["filters"] if col == "child_id"}
            if call["op"] == "insert":
                payload_child = (call["payload"] or {}).get("child_id")
                if payload_child:
                    seen.add(payload_child)
            assert seen <= {CHILD_ID}, f"a {call['table']} {call['op']} touched another recipient"


def test_post_pulse_evaluation_clears_a_resolved_alert(monkeypatch):
    # No pressure now, healthy LCI, but an old active L1 row exists -> compute None ->
    # the row is deleted (the alert clears).
    fake = _history_fake(
        activities=[],
        pulses=[],
        snapshots=[],
        alert_select=[
            {
                "chapter": "career",
                "level": 1,
                "trigger_condition": "l1_counts_30d",
                "dismissed": False,
                "dismissed_level": None,
            }
        ],
        lci_pulses=[],
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    level = alerts_service.evaluate_chapter_alert(AUTHED, "career", CHILD_ID, now=NOW)
    assert level is None
    deletes = [c for c in fake.calls if c["op"] == "delete" and c["table"] == "alert_record"]
    assert len(deletes) == 1
    # The delete was scoped to this recipient (it cannot clear another recipient's alert).
    assert ("child_id", CHILD_ID) in deletes[0]["filters"]


def test_post_pulse_evaluation_is_non_interrupting_on_failure(monkeypatch):
    # If the alert evaluation raises (e.g. a read blows up), the _safe wrapper must
    # swallow it so the pulse flow is never broken.
    def _boom(user, chapter, child_id, **kwargs):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(alerts_service, "evaluate_chapter_alert", _boom)
    # Must not raise.
    alerts_service.evaluate_chapter_alert_safe(AUTHED, "career", CHILD_ID, now=NOW)


# ---------------------------------------------------------------------------
# SERVICE: dismissal + worsen-past-the-next-threshold re-trigger (section 4.9)
# ---------------------------------------------------------------------------


def test_dismiss_marks_the_row_dismissed_at_its_level(monkeypatch):
    # dismiss_alert resolves the sole recipient first, then dismisses only that
    # recipient's alert for the chapter (scoped by child_id, migration 0010).
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([CHILD_ROW]),
            ("alert_record", "select"): FakeResponse(
                [
                    {
                        "chapter": "career",
                        "level": 1,
                        "trigger_condition": "l1_counts_30d",
                        "dismissed": False,
                        "dismissed_level": None,
                    }
                ]
            ),
            ("alert_record", "update"): FakeResponse([{"id": "al-1"}]),
        }
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    result = alerts_service.dismiss_alert(AUTHED, "career")
    assert result.chapter == "career"
    assert result.dismissed_level == 1
    update = [c for c in fake.calls if c["op"] == "update" and c["table"] == "alert_record"][0]
    assert update["payload"] == {"dismissed": True, "dismissed_level": 1}
    # The dismiss update was scoped to this recipient (never another recipient's alert).
    assert ("child_id", CHILD_ID) in update["filters"]


def test_dismiss_with_no_active_alert_raises(monkeypatch):
    fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([CHILD_ROW]),
            ("alert_record", "select"): FakeResponse([]),
        }
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)
    with pytest.raises(alerts_service.AlertNotFoundError):
        alerts_service.dismiss_alert(AUTHED, "career")


def test_dismissed_alert_does_not_return_at_the_same_level(monkeypatch):
    # An L1 was dismissed (dismissed_level 1). Conditions still only meet L1 -> the
    # alert stays hidden: the row is UPDATED (latent level tracked) but NOT re-activated
    # (dismissed stays true, so it is absent from the active list).
    activities = [{"tier": "Modified", "created_at": _iso(5)} for _ in range(3)]
    pulses = [{"outcome_code": "okay", "created_at": _iso(5)} for _ in range(3)]
    lci_rows = [
        {
            "chapter": "career",
            "outcome_code": "okay",
            "tier_recommended": "Modified",
            "created_at": _iso(5),
        }
        for _ in range(3)
    ]
    fake = _history_fake(
        activities=activities,
        pulses=pulses,
        snapshots=[],
        alert_select=[
            {
                "chapter": "career",
                "level": 1,
                "trigger_condition": "l1_counts_30d",
                "dismissed": True,
                "dismissed_level": 1,
            }
        ],
        lci_pulses=lci_rows,
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    level = alerts_service.evaluate_chapter_alert(AUTHED, "career", CHILD_ID, now=NOW)
    assert level is AlertLevel.L1  # the engine still computes L1
    update = [c for c in fake.calls if c["op"] == "update" and c["table"] == "alert_record"][0]
    # The latent level is tracked, but dismissed is NOT cleared (it stays hidden).
    assert update["payload"]["level"] == 1
    assert "dismissed" not in update["payload"]
    assert ("child_id", CHILD_ID) in update["filters"]


def test_dismissed_alert_returns_when_it_worsens_past_the_next_threshold(monkeypatch):
    # An L1 was dismissed (dismissed_level 1). Conditions now reach L3 (LCI < 30) ->
    # strictly higher than the dismissed level -> the alert RE-ACTIVATES at L3.
    fake = _history_fake(
        activities=[],
        pulses=[],
        snapshots=[],
        alert_select=[
            {
                "chapter": "career",
                "level": 1,
                "trigger_condition": "l1_counts_30d",
                "dismissed": True,
                "dismissed_level": 1,
            }
        ],
        # One Difficult/Full pulse drops the LCI to 42... not < 30. Use several to push
        # below 30: four Difficult/Full from 50 -> 42 -> 34 -> 26 (clamped fold).
        lci_pulses=[
            {
                "chapter": "career",
                "outcome_code": "difficult",
                "tier_recommended": "Full",
                "created_at": _iso(d),
            }
            for d in (8, 7, 6, 5)
        ],
    )
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    level = alerts_service.evaluate_chapter_alert(AUTHED, "career", CHILD_ID, now=NOW)
    assert level is AlertLevel.L3
    update = [c for c in fake.calls if c["op"] == "update" and c["table"] == "alert_record"][0]
    # Re-activated at the higher level: dismissed cleared, level bumped to 3.
    assert update["payload"]["level"] == 3
    assert update["payload"]["dismissed"] is False
    assert update["payload"]["dismissed_level"] is None
    assert ("child_id", CHILD_ID) in update["filters"]
