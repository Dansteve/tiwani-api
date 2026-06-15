"""No-DB tests for the check-in history endpoint (GET /api/v1/lci/history) + its service.

The read behind the "Your check-in history" view (the de-risked timeline, the
researcher's build-with-conditions verdict). Two layers, both off a live Supabase
(blocked in the sandbox; mocked with the fake client):

  - ROUTE wiring (TestClient against main.app): auth required (401), and the
    not-owned-recipient path is a 404 (the resolver raises ChildNotFoundError).
  - SERVICE (the real LCI engine, a fake Supabase client): get_anon_client is patched
    with a FakeClient so the REAL read folds scripted lci_snapshot rows into discrete
    points with their section 4.3 bands, reconstructs the overall series, and derives the
    honesty signals (reading_count, latest_taken_at, is_stale). It pins:
      - discrete points carry the real instant + the api-owned band, time-ascending;
      - the three-reading floor is reading_count (the api owns it; the app draws no line
        below 3);
      - stale = stop: is_stale flips once the last reading is older than the window, but a
        fresh reading is not stale;
      - the overall series is the equal-weighted overall reconstructed at each distinct
        snapshot instant, never a re-scored value;
      - every snapshot read is scoped to the resolved recipient (the isolation rule), so a
        second recipient's history can never leak in.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.services.lci as lci_service
from app.auth import AuthedUser, get_current_user
from app.services.profile import ChildNotFoundError
from tests.fakes_supabase import FakeClient, FakeResponse

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# The caller's sole care recipient. lci_history resolves it via profile.resolve_child_id,
# which reads child_profile when no explicit child_id is given; the snapshot read then scopes
# every lci_snapshot select to this child_id (the isolation rule).
CHILD_ID = "ch-1"
CHILD_ROW = {"id": CHILD_ID, "user_id": "u-1", "name": "Sam"}


@pytest.fixture
def authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


def _fake_with_snapshots(snapshots, child_rows=(CHILD_ROW,)):
    """A FakeClient scripted with the recipient + its lci_snapshot rows (the history read)."""
    return FakeClient(
        {
            ("child_profile", "select"): FakeResponse(list(child_rows)),
            ("lci_snapshot", "select"): FakeResponse(list(snapshots)),
        }
    )


# ---------------------------------------------------------------------------
# ROUTE: auth + 404
# ---------------------------------------------------------------------------


def test_history_requires_authentication(client):
    assert client.get("/api/v1/lci/history").status_code == 401


def test_history_unknown_child_id_is_404(authed, monkeypatch):
    def _raise(user, child_id):
        raise ChildNotFoundError("nope")

    monkeypatch.setattr(lci_service, "resolve_child_id", _raise)
    response = authed.get("/api/v1/lci/history?child_id=not-mine")
    assert response.status_code == 404


def test_history_route_serializes_the_payload_shape(authed, monkeypatch):
    # A travel chapter with three readings (60, 64, 70) -> three discrete points, bands set.
    snapshots = [
        {"chapter": "travel", "score": 60, "taken_at": "2026-06-14T09:00:00+00:00"},
        {"chapter": "travel", "score": 64, "taken_at": "2026-06-16T09:00:00+00:00"},
        {"chapter": "travel", "score": 70, "taken_at": "2026-06-18T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    body = authed.get("/api/v1/lci/history").json()

    assert set(body.keys()) == {"overall", "chapters", "generated_at"}
    assert {s["scope"] for s in body["chapters"]} == {
        "school",
        "career",
        "family",
        "social",
        "travel",
        "culture",
    }
    travel = next(s for s in body["chapters"] if s["scope"] == "travel")
    assert set(travel.keys()) == {
        "scope",
        "points",
        "reading_count",
        "latest_taken_at",
        "is_stale",
    }
    assert travel["reading_count"] == 3
    # Each point is a discrete instant + score + band (a zone, never a precise altitude).
    assert [p["score"] for p in travel["points"]] == [60, 64, 70]
    assert [p["band"] for p in travel["points"]] == ["stable", "stable", "stable"]
    assert all(set(p.keys()) == {"taken_at", "score", "band"} for p in travel["points"])
    assert body["overall"]["scope"] == "overall"


# ---------------------------------------------------------------------------
# SERVICE: discrete points + bands, time order
# ---------------------------------------------------------------------------


def test_chapter_series_are_discrete_points_in_time_order_with_bands(monkeypatch):
    # family crosses bands: 70 (stable) -> 45 (pressure) -> 20 (critical). The points are the
    # real instants in ascending order, each carrying its section 4.3 band; the api owns the
    # band, the app reads each as a zone (never a plotted altitude).
    snapshots = [
        {"chapter": "family", "score": 20, "taken_at": "2026-06-18T09:00:00+00:00"},
        {"chapter": "family", "score": 70, "taken_at": "2026-06-14T09:00:00+00:00"},
        {"chapter": "family", "score": 45, "taken_at": "2026-06-16T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    family = next(s for s in history.chapters if s.scope == "family")

    assert [p.score for p in family.points] == [70, 45, 20]  # sorted by instant
    assert [p.band for p in family.points] == ["stable", "pressure", "critical"]
    # The timestamps are the REAL recorded instants, ascending (no interpolation).
    assert [p.taken_at.isoformat() for p in family.points] == [
        "2026-06-14T09:00:00+00:00",
        "2026-06-16T09:00:00+00:00",
        "2026-06-18T09:00:00+00:00",
    ]


def test_a_chapter_with_no_reading_is_an_empty_series(monkeypatch):
    fake = _fake_with_snapshots([])
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    # Every one of the six chapters is present and empty (no points, not stale, no latest).
    assert len(history.chapters) == 6
    for series in history.chapters:
        assert series.points == []
        assert series.reading_count == 0
        assert series.latest_taken_at is None
        assert series.is_stale is False
    assert history.overall.points == []
    assert history.overall.reading_count == 0


# ---------------------------------------------------------------------------
# SERVICE: the three-reading floor (reading_count, owned by the api)
# ---------------------------------------------------------------------------


def test_reading_count_is_the_floor_below_three(monkeypatch):
    # Two readings: reading_count is 2 (below the floor of 3). The api owns this number; the
    # app draws NO line/slope below 3. The service emits both discrete points, never a trend.
    snapshots = [
        {"chapter": "school", "score": 50, "taken_at": "2026-06-16T09:00:00+00:00"},
        {"chapter": "school", "score": 58, "taken_at": "2026-06-18T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    school = next(s for s in history.chapters if s.scope == "school")
    assert school.reading_count == 2
    assert len(school.points) == 2  # two dots, never joined into a trend


# ---------------------------------------------------------------------------
# SERVICE: stale = stop, do not lie (latest_taken_at + is_stale)
# ---------------------------------------------------------------------------


def test_a_fresh_reading_is_not_stale(monkeypatch):
    # Last reading 4 days before NOW (inside the 14-day window): not stale, the series is live.
    snapshots = [
        {"chapter": "career", "score": 55, "taken_at": "2026-06-12T09:00:00+00:00"},
        {"chapter": "career", "score": 61, "taken_at": "2026-06-16T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    career = next(s for s in history.chapters if s.scope == "career")
    assert career.is_stale is False
    assert career.latest_taken_at.isoformat() == "2026-06-16T09:00:00+00:00"


def test_an_old_series_is_flagged_stale_so_the_view_stops(monkeypatch):
    # Last reading 20 days before NOW (past the 14-day window): is_stale True. The app then
    # degrades to "no reading since [latest_taken_at]" instead of carrying the score forward.
    snapshots = [
        {"chapter": "social", "score": 48, "taken_at": "2026-05-25T09:00:00+00:00"},
        {"chapter": "social", "score": 52, "taken_at": "2026-05-31T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    social = next(s for s in history.chapters if s.scope == "social")
    assert social.is_stale is True
    assert social.latest_taken_at.isoformat() == "2026-05-31T09:00:00+00:00"
    # The last point is the last REAL reading; nothing is appended after it (no carry-forward).
    assert social.points[-1].taken_at.isoformat() == "2026-05-31T09:00:00+00:00"


# ---------------------------------------------------------------------------
# SERVICE: the overall series is reconstructed, equal-weighted, per instant
# ---------------------------------------------------------------------------


def test_overall_series_is_the_equal_weighted_overall_per_instant(monkeypatch):
    # travel reads 60 (day 14), family reads 40 (day 16). The overall:
    #   - at day 14 only travel exists -> mean(60) = 60.
    #   - at day 16 travel still 60, family 40 -> mean(60, 40) = 50.
    # Two distinct overall values -> two points; no chapter is dragged down to zero (a
    # chapter with no snapshot yet is excluded, not counted as 0).
    snapshots = [
        {"chapter": "travel", "score": 60, "taken_at": "2026-06-14T09:00:00+00:00"},
        {"chapter": "family", "score": 40, "taken_at": "2026-06-16T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    overall = history.overall
    assert [p.score for p in overall.points] == [60, 50]
    assert [p.taken_at.isoformat() for p in overall.points] == [
        "2026-06-14T09:00:00+00:00",
        "2026-06-16T09:00:00+00:00",
    ]
    assert overall.reading_count == 2


def test_overall_series_collapses_unchanged_values(monkeypatch):
    # Two chapters both reading 60 at two instants: the overall stays 60 throughout, so only
    # ONE point is emitted (the moment it first held), never a dense restatement of 60, 60.
    snapshots = [
        {"chapter": "travel", "score": 60, "taken_at": "2026-06-14T09:00:00+00:00"},
        {"chapter": "school", "score": 60, "taken_at": "2026-06-16T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    assert [p.score for p in history.overall.points] == [60]


# ---------------------------------------------------------------------------
# SERVICE: the isolation rule (RLS + per-recipient scoping)
# ---------------------------------------------------------------------------


def test_every_snapshot_read_is_scoped_to_the_resolved_recipient(monkeypatch):
    snapshots = [
        {"chapter": "travel", "score": 60, "taken_at": "2026-06-16T09:00:00+00:00"},
    ]
    fake = _fake_with_snapshots(snapshots)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    lci_service.lci_history(AUTHED, now=NOW)

    snapshot_selects = [
        c for c in fake.calls if c["table"] == "lci_snapshot" and c["op"] == "select"
    ]
    assert snapshot_selects  # the read DID issue a snapshot select
    # Every snapshot read filtered by BOTH the user and the resolved recipient, so a second
    # recipient's history (a different child_id) can never be pooled into this one.
    for call in snapshot_selects:
        assert ("user_id", AUTHED.id) in call["filters"]
        assert ("child_id", CHILD_ID) in call["filters"]


def test_no_recipient_yet_reads_no_snapshots(monkeypatch):
    # A fresh user with NO recipient: resolve_child_id returns None, the snapshot read is
    # skipped entirely (nothing pooled), and every series is empty.
    fake = _fake_with_snapshots([], child_rows=[])
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: fake)

    history = lci_service.lci_history(AUTHED, now=NOW)
    assert all(s.points == [] for s in history.chapters)
    assert history.overall.points == []
    # No recipient: the per-recipient snapshot read never ran.
    assert not any(c["table"] == "lci_snapshot" for c in fake.calls)
