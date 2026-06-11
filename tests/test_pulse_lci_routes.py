"""No-DB tests for the v3 Pulse + LCI endpoints and the now-live dashboard LCI.

Two layers, both off a live Supabase (blocked in the sandbox; the task requires
mocking):

  - ROUTE wiring (TestClient against main.app): the current-user dependency is
    overridden for the authed cases (left real for the 401 cases), and the service
    is monkeypatched, so the parse -> validate -> call-service -> serialize path and
    the 401/404/409 contract are what is tested.

  - SERVICE (the real LCI engine, a fake Supabase client): get_anon_client is patched
    with a FakeClient so the REAL section 4.8 fold runs over scripted pulse rows, the
    pulse INSERT and the lci_snapshot INSERT are recorded, and the dashboard / LCI
    services read the scripted rows back. This pins the recording flow, the stored-
    tier rule, and that the dashboard LCI is now live.

It also pins the exact PulseRecord / ChapterLci / OverallLci shapes the app mirrors.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.routes.pulses as pulses_routes
import app.services.chapters as chapters_service
import app.services.lci as lci_service
import app.services.pulse as pulse_service
from app.auth import AuthedUser, get_current_user
from app.models.pulse import PulseRecord
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# A stored activity_record the Pulse reads its chapter + tier from.
ACTIVITY_ROW = {"id": "act-1", "chapter": "travel", "tier": "Modified"}


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
        ("post", "/api/v3/pulses"),
        ("get", "/api/v3/pulses/pending"),
        ("get", "/api/v3/lci/overall"),
        ("get", "/api/v3/lci/chapters"),
    ],
)
def test_pulse_and_lci_routes_require_authentication(client, method, path):
    if method == "get":
        response = client.get(path)
    else:
        response = client.post(path, json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /pulses route wiring (service monkeypatched)
# ---------------------------------------------------------------------------

SAMPLE_PULSE = PulseRecord(
    id="p-1",
    activity_id="act-1",
    outcome_code="well",
    challenge_dimension=None,
    tier_recommended="Modified",
    chapter="travel",
    timestamp=NOW,
)


def test_create_pulse_success_returns_the_record_shape(authed, monkeypatch):
    monkeypatch.setattr(
        pulses_routes.pulse_service,
        "record_pulse",
        lambda user, **kwargs: SAMPLE_PULSE,
    )
    response = authed.post(
        "/api/v3/pulses",
        json={"activity_id": "act-1", "outcome_code": "well"},
    )
    assert response.status_code == 200
    body = response.json()
    # The PulseRecord contract the app mirrors (plus the additive tier_recommended).
    assert set(body.keys()) == {
        "id",
        "activity_id",
        "outcome_code",
        "challenge_dimension",
        "tier_recommended",
        "chapter",
        "timestamp",
    }
    assert body["outcome_code"] == "well"
    assert body["chapter"] == "travel"


def test_create_pulse_unknown_activity_is_404(authed, monkeypatch):
    def _raise(user, **kwargs):
        raise pulse_service.ActivityNotFoundError("nope")

    monkeypatch.setattr(pulses_routes.pulse_service, "record_pulse", _raise)
    response = authed.post(
        "/api/v3/pulses",
        json={"activity_id": "ghost", "outcome_code": "well"},
    )
    assert response.status_code == 404


def test_create_pulse_duplicate_is_409(authed, monkeypatch):
    def _raise(user, **kwargs):
        raise pulse_service.AlreadyPulsedError("dup")

    monkeypatch.setattr(pulses_routes.pulse_service, "record_pulse", _raise)
    response = authed.post(
        "/api/v3/pulses",
        json={"activity_id": "act-1", "outcome_code": "okay"},
    )
    assert response.status_code == 409


def test_create_pulse_rejects_an_unknown_outcome_422(authed):
    response = authed.post(
        "/api/v3/pulses",
        json={"activity_id": "act-1", "outcome_code": "great"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# SERVICE: record_pulse reads the stored tier, writes the pulse + a snapshot
# ---------------------------------------------------------------------------


def _alerts_fake_quiet():
    """A FakeClient for the post-pulse alert hook that yields NO alert (quiet).

    The Pulse service now evaluates Erosion Alerts after the LCI recompute (Task 7,
    section 4.9), through app.services.alerts (its own get_anon_client). For the
    pulse-WRITE tests, which assert the pulse + snapshot writes (not alerting), the
    alert hook is pointed here: empty activity / pulse / snapshot / alert reads mean
    the engine computes no level and nothing is written. This keeps the hook a real,
    exercised, non-interrupting step without coupling the assertions to alert state.
    """
    return FakeClient(
        {
            ("activity_record", "select"): FakeResponse([]),
            ("pulse_record", "select"): FakeResponse([]),
            ("lci_snapshot", "select"): FakeResponse([]),
            ("alert_record", "select"): FakeResponse([]),
        }
    )


def _fake_for_pulse_write():
    """Script the activity read, the no-existing-pulse check, the pulse insert, and
    the snapshot insert. The post-insert recompute re-reads pulse_record (select):
    the recorded pulse is the single row, so the chapter score is 50 + 7 = 57.
    """
    return FakeClient(
        {
            ("activity_record", "select"): FakeResponse([ACTIVITY_ROW]),
            ("pulse_record", "select"): [
                FakeResponse([]),  # the duplicate check: none yet
                FakeResponse(  # the recompute's pulse fetch: the one just inserted
                    [
                        {
                            "chapter": "travel",
                            "outcome_code": "well",
                            "tier_recommended": "Modified",
                            "created_at": "2026-06-20T12:00:00+00:00",
                        }
                    ]
                ),
            ],
            ("pulse_record", "insert"): FakeResponse(
                [
                    {
                        "id": "p-1",
                        "activity_id": "act-1",
                        "outcome_code": "well",
                        "challenge_dimension": None,
                        "created_at": "2026-06-20T12:00:00+00:00",
                    }
                ]
            ),
            ("lci_snapshot", "insert"): FakeResponse([{"id": "s-1"}]),
        }
    )


def test_record_pulse_reads_stored_tier_and_writes_pulse_and_snapshot(monkeypatch):
    fake = _fake_for_pulse_write()
    monkeypatch.setattr("app.services.pulse.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr(
        "app.services.alerts.get_anon_client", lambda token=None: _alerts_fake_quiet()
    )

    record = pulse_service.record_pulse(
        AUTHED,
        activity_id="act-1",
        outcome_code="well",
        now=NOW,
    )

    # The record carries the STORED tier + chapter (read from the activity_record),
    # never re-derived.
    assert record.tier_recommended == "Modified"
    assert record.chapter == "travel"
    assert record.outcome_code == "well"

    # A pulse_record INSERT was issued, scoped to the user, carrying the stored tier.
    pulse_inserts = [c for c in fake.calls if c["op"] == "insert" and c["table"] == "pulse_record"]
    assert len(pulse_inserts) == 1
    payload = pulse_inserts[0]["payload"]
    assert payload["user_id"] == "u-1"
    assert payload["activity_id"] == "act-1"
    assert payload["chapter"] == "travel"
    assert payload["tier_recommended"] == "Modified"
    assert payload["outcome_code"] == "well"

    # The post-pulse recompute wrote an lci_snapshot with the new chapter score
    # (50 + 7 = 57 for Well on a Modified activity).
    snap_inserts = [c for c in fake.calls if c["op"] == "insert" and c["table"] == "lci_snapshot"]
    assert len(snap_inserts) == 1
    snap = snap_inserts[0]["payload"]
    assert snap["user_id"] == "u-1"
    assert snap["chapter"] == "travel"
    assert snap["score"] == 57


def test_record_pulse_unknown_activity_raises(monkeypatch):
    fake = FakeClient({("activity_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.pulse.get_anon_client", lambda token=None: fake)
    with pytest.raises(pulse_service.ActivityNotFoundError):
        pulse_service.record_pulse(AUTHED, activity_id="ghost", outcome_code="well", now=NOW)


def test_record_pulse_duplicate_raises(monkeypatch):
    fake = FakeClient(
        {
            ("activity_record", "select"): FakeResponse([ACTIVITY_ROW]),
            ("pulse_record", "select"): FakeResponse([{"id": "p-existing"}]),
        }
    )
    monkeypatch.setattr("app.services.pulse.get_anon_client", lambda token=None: fake)
    with pytest.raises(pulse_service.AlreadyPulsedError):
        pulse_service.record_pulse(AUTHED, activity_id="act-1", outcome_code="okay", now=NOW)


def test_skipped_pulse_records_with_zero_effect_score(monkeypatch):
    # A skipped pulse is recorded; the recompute's fold leaves the chapter at its
    # start 50 (skipped = 0). The snapshot captures 50.
    fake = FakeClient(
        {
            ("activity_record", "select"): FakeResponse([ACTIVITY_ROW]),
            ("pulse_record", "select"): [
                FakeResponse([]),  # no existing pulse
                FakeResponse(  # the recompute fetch: one skipped pulse
                    [
                        {
                            "chapter": "travel",
                            "outcome_code": "skipped",
                            "tier_recommended": "Modified",
                            "created_at": "2026-06-20T12:00:00+00:00",
                        }
                    ]
                ),
            ],
            ("pulse_record", "insert"): FakeResponse(
                [
                    {
                        "id": "p-2",
                        "activity_id": "act-1",
                        "outcome_code": "skipped",
                        "challenge_dimension": None,
                        "created_at": "2026-06-20T12:00:00+00:00",
                    }
                ]
            ),
            ("lci_snapshot", "insert"): FakeResponse([{"id": "s-2"}]),
        }
    )
    monkeypatch.setattr("app.services.pulse.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr(
        "app.services.alerts.get_anon_client", lambda token=None: _alerts_fake_quiet()
    )

    pulse_service.record_pulse(AUTHED, activity_id="act-1", outcome_code="skipped", now=NOW)

    snap = [c for c in fake.calls if c["op"] == "insert" and c["table"] == "lci_snapshot"][0]
    assert snap["payload"]["score"] == 50  # skipped moved the score by 0


# ---------------------------------------------------------------------------
# GET /pulses/pending
# ---------------------------------------------------------------------------


def test_pending_pulses_are_overdue_activities_without_a_pulse(monkeypatch):
    # Three activities: act-a is overdue + unpulsed (pending), act-b is overdue but
    # already pulsed (not pending), act-c is not yet due (not pending).
    activities = [
        {
            "id": "act-a",
            "activity_name": "Airport departure",
            "chapter": "travel",
            "scheduled_pulse_at": "2026-06-19T09:00:00+00:00",  # before NOW
        },
        {
            "id": "act-b",
            "activity_name": "Bedtime routine",
            "chapter": "family",
            "scheduled_pulse_at": "2026-06-18T09:00:00+00:00",  # before NOW, but pulsed
        },
        {
            "id": "act-c",
            "activity_name": "School trip",
            "chapter": "school",
            "scheduled_pulse_at": "2026-06-25T09:00:00+00:00",  # after NOW
        },
    ]
    fake = FakeClient(
        {
            ("activity_record", "select"): FakeResponse(activities),
            ("pulse_record", "select"): FakeResponse([{"activity_id": "act-b"}]),
        }
    )
    monkeypatch.setattr("app.services.pulse.get_anon_client", lambda token=None: fake)

    pending = pulse_service.list_pending_pulses(AUTHED, now=NOW)
    ids = [p.activity_id for p in pending]
    assert ids == ["act-a"]  # only the overdue, unpulsed one
    assert pending[0].chapter == "travel"


# ---------------------------------------------------------------------------
# LCI service: the overall + per-chapter index over scripted pulses
# ---------------------------------------------------------------------------


def test_chapter_lci_list_folds_scripted_pulses(monkeypatch):
    # travel: Well/Modified (+7) then Okay/Modified (+5) from 50 -> 62, 2 pulses
    # (sparse, "building your picture"). family: one Difficult/Full (-8) from 50 ->
    # 42, 1 pulse. Other chapters: no pulse -> score null, "--".
    pulses = [
        {
            "chapter": "travel",
            "outcome_code": "well",
            "tier_recommended": "Modified",
            "created_at": "2026-06-10T09:00:00+00:00",
        },
        {
            "chapter": "travel",
            "outcome_code": "okay",
            "tier_recommended": "Modified",
            "created_at": "2026-06-12T09:00:00+00:00",
        },
        {
            "chapter": "family",
            "outcome_code": "difficult",
            "tier_recommended": "Full",
            "created_at": "2026-06-11T09:00:00+00:00",
        },
    ]
    fake = FakeClient(
        {
            ("pulse_record", "select"): FakeResponse(pulses),
            ("lci_snapshot", "select"): FakeResponse([]),  # no prior snapshots
        }
    )
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    chapters = {c.chapter: c for c in lci_service.chapter_lci_list(AUTHED, now=NOW)}

    assert chapters["travel"].score == 62
    assert chapters["travel"].pulse_count == 2
    assert chapters["travel"].label == "building your picture"  # < 3 pulses
    assert chapters["family"].score == 42
    assert chapters["family"].pulse_count == 1
    # A chapter with no pulse: null score, "--" label, building_picture trajectory.
    assert chapters["school"].score is None
    assert chapters["school"].pulse_count == 0
    assert chapters["school"].label == "--"
    # use_enum_values serializes trajectory to its string code on the wire.
    assert chapters["school"].trajectory == "building_picture"


def test_overall_lci_excludes_no_data_chapters(monkeypatch):
    # travel = 62 (2 pulses), family = 42 (1 pulse), rest none. Overall = mean(62, 42)
    # = 52, NOT dragged down by the four no-data chapters.
    pulses = [
        {
            "chapter": "travel",
            "outcome_code": "well",
            "tier_recommended": "Modified",
            "created_at": "2026-06-10T09:00:00+00:00",
        },
        {
            "chapter": "travel",
            "outcome_code": "okay",
            "tier_recommended": "Modified",
            "created_at": "2026-06-12T09:00:00+00:00",
        },
        {
            "chapter": "family",
            "outcome_code": "difficult",
            "tier_recommended": "Full",
            "created_at": "2026-06-11T09:00:00+00:00",
        },
    ]
    fake = FakeClient(
        {
            ("pulse_record", "select"): FakeResponse(pulses),
            ("lci_snapshot", "select"): FakeResponse([]),
        }
    )
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    overall = lci_service.overall_lci(AUTHED, now=NOW)
    assert overall.score == 52  # mean(62, 42)
    assert set(c for c in overall.chapters_included) == {"travel", "family"}


def test_overall_lci_is_null_for_a_fresh_user(monkeypatch):
    fake = FakeClient(
        {
            ("pulse_record", "select"): FakeResponse([]),
            ("lci_snapshot", "select"): FakeResponse([]),
        }
    )
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    overall = lci_service.overall_lci(AUTHED, now=NOW)
    assert overall.score is None
    assert overall.chapters_included == []
    assert overall.label == "--"
    assert overall.trajectory == "building_picture"


def test_chapter_trajectory_uses_the_seven_day_prior_snapshot(monkeypatch):
    # travel current: Well/Modified x3 from 50 -> 71 (3 pulses, not sparse). A prior
    # snapshot of 60 taken before (NOW - 7 days) -> +11 -> strengthening.
    pulses = [
        {
            "chapter": "travel",
            "outcome_code": "well",
            "tier_recommended": "Modified",
            "created_at": f"2026-06-1{d}T09:00:00+00:00",
        }
        for d in (4, 5, 6)
    ]
    # The snapshot taken 2026-06-10 is before the look-back instant (NOW - 7d =
    # 2026-06-13), so it is the prior point the trajectory compares against.
    snapshots = [
        {"chapter": "travel", "score": 60, "taken_at": "2026-06-10T09:00:00+00:00"},
    ]
    fake = FakeClient(
        {
            ("pulse_record", "select"): FakeResponse(pulses),
            ("lci_snapshot", "select"): FakeResponse(snapshots),
        }
    )
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)

    chapters = {c.chapter: c for c in lci_service.chapter_lci_list(AUTHED, now=NOW)}
    assert chapters["travel"].score == 71
    assert chapters["travel"].pulse_count == 3
    assert chapters["travel"].label is None  # 3 pulses, no sparse label
    assert chapters["travel"].trajectory == "strengthening"  # 71 vs prior 60 = +11


# ---------------------------------------------------------------------------
# DASHBOARD: ChapterStatus.lci is now live (the same fold)
# ---------------------------------------------------------------------------


def test_chapters_dashboard_now_returns_the_real_lci(monkeypatch):
    # The dashboard reads activity_record (for counts) AND now pulse_record (for the
    # LCI). travel has one prepared activity and one Well/Modified pulse -> lci 57.
    activity_rows = [{"chapter": "travel", "created_at": "2026-06-11T09:00:00+00:00"}]
    pulse_rows = [
        {
            "chapter": "travel",
            "outcome_code": "well",
            "tier_recommended": "Modified",
            "created_at": "2026-06-11T09:00:00+00:00",
        }
    ]
    chapters_fake = FakeClient({("activity_record", "select"): FakeResponse(activity_rows)})
    lci_fake = FakeClient({("pulse_record", "select"): FakeResponse(pulse_rows)})
    # Since Task 7, the dashboard reads the user's active alerts too; none here.
    alerts_fake = FakeClient({("alert_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.chapters.get_anon_client", lambda token=None: chapters_fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: lci_fake)
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: alerts_fake)

    statuses = {s.chapter: s for s in chapters_service.list_chapter_statuses(AUTHED)}
    assert statuses["travel"].activity_count == 1
    assert statuses["travel"].lci == 57  # the now-live section 4.8 score
    assert statuses["travel"].alert_level is None  # no active alert raised
    # A chapter with no pulse stays null (not 0).
    assert statuses["school"].lci is None
