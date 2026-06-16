"""No-DB tests for the v3 six-chapter dashboard endpoint and its schema.

The route tests drive the real FastAPI app (main.app) through a TestClient. Two
seams: the current-user dependency is overridden with a fixed AuthedUser for the
authenticated case (left real for the 401 case, which short-circuits before any
Supabase call), and since Task 5 the chapters service reads the user's
activity_record rows (for activity_count / last_prepared_at), so the authed
fixture stubs get_anon_client with a fake returning an empty activity_record
select. These assert the fresh-user baseline, so the six chapters still come back
not-started, with no live Supabase (blocked in the sandbox; the task requires
mocking).

They pin the cross-repo contract for GET /api/v1/chapters: auth required (401),
exactly the six chapters in a stable order, all null/0 for a fresh user, and the
correct codes + display names. The schema tests pin the ChapterStatus shape and
the code/name mapping the app mirrors exactly.
"""

import pytest

from app.auth import AuthedUser, get_current_user
from app.models.chapters import (
    CHAPTER_DISPLAY_NAMES,
    Chapter,
    ChapterStatus,
)
from tests.fakes_supabase import FakeClient, FakeResponse

AUTHED = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# The contract, in order. School is first-class and first (the prototype's missing
# School is corrected). Display names are the PRD section 4.3 labels.
EXPECTED_CHAPTERS = [
    ("school", "School"),
    ("career", "Career"),
    ("family", "Family Life & Routine"),
    ("social", "Social & Community"),
    ("travel", "Travel & Holiday"),
    ("culture", "Culture & Faith"),
]


@pytest.fixture
def authed(client, monkeypatch):
    """Override the current-user dependency and stub the chapters service clients.

    Since Task 5, the chapters service reads the user's activity_record rows (to
    fill activity_count / last_prepared_at); since Task 6 it also reads the user's
    pulse_record rows through the LCI service (to fill the chapter LCI); since Task 7
    it also reads the user's alert_record rows through the alerts service (to fill
    alert_level). So the authed route tests mock ALL THREE Supabase clients. These
    tests assert the FRESH-user baseline, so the fakes return an empty activity_record
    select, an empty pulse_record select, and an empty alert_record select: every
    chapter stays not-started (count 0, no timestamp, no LCI, no alert). The populated
    wiring is tested against rows in tests/test_plans_routes.py and
    tests/test_pulse_lci_routes.py.
    """
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    # The dashboard now resolves the caller's care recipient first (profile layer). For
    # the fresh-user baseline there is NO recipient yet: the resolver returns None, so the
    # per-recipient reads are skipped and every chapter stays not-started. The empty
    # child_profile select is served from the chapters client (which the resolver shares).
    chapters_fake = FakeClient(
        {
            ("child_profile", "select"): FakeResponse([]),
            ("activity_record", "select"): FakeResponse([]),
        }
    )
    lci_fake = FakeClient({("pulse_record", "select"): FakeResponse([])})
    alerts_fake = FakeClient({("alert_record", "select"): FakeResponse([])})
    monkeypatch.setattr("app.services.chapters.get_anon_client", lambda token=None: chapters_fake)
    monkeypatch.setattr("app.services.lci.get_anon_client", lambda token=None: lci_fake)
    monkeypatch.setattr("app.services.alerts.get_anon_client", lambda token=None: alerts_fake)
    monkeypatch.setattr("app.services.profile.get_anon_client", lambda token=None: chapters_fake)
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required (401): real dependency, no token
# ---------------------------------------------------------------------------


def test_chapters_requires_authentication(client):
    # No Authorization header => the current-user dependency raises 401 before any
    # Supabase call (it short-circuits on missing credentials).
    response = client.get("/api/v1/chapters")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/chapters (fresh user)
# ---------------------------------------------------------------------------


def test_chapters_returns_exactly_six(authed):
    response = authed.get("/api/v1/chapters")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 6


def test_chapters_are_in_stable_order_with_correct_codes_and_names(authed):
    body = authed.get("/api/v1/chapters").json()
    assert [(c["chapter"], c["display_name"]) for c in body] == EXPECTED_CHAPTERS


def test_chapters_are_all_not_started_for_a_fresh_user(authed):
    # A fresh user has no activities, LCI, or alerts yet (Tasks 5 to 7), so every
    # chapter is the "not started" baseline: lci/alert_level/last_prepared_at null
    # and activity_count 0. The api returns raw inputs only; the app maps these to
    # grey per section 4.3 (the api never sends a colour).
    body = authed.get("/api/v1/chapters").json()
    for chapter in body:
        assert chapter["lci"] is None
        assert chapter["alert_level"] is None
        assert chapter["last_prepared_at"] is None
        assert chapter["activity_count"] == 0


def test_chapters_payload_carries_exactly_the_contract_fields(authed):
    body = authed.get("/api/v1/chapters").json()
    expected_keys = {
        "chapter",
        "display_name",
        "lci",
        "alert_level",
        "last_prepared_at",
        "activity_count",
        "engagement",
    }
    for chapter in body:
        assert set(chapter.keys()) == expected_keys


def test_chapters_engagement_is_null_for_a_fresh_user(authed):
    # The engagement signal (the owner's "disengagement" idea) carries NO copy for a chapter
    # with no plan ever: zero activity is the existing not-started, never quiet/resting. So a
    # fresh user sees engagement=null on every chapter regardless of the flag.
    body = authed.get("/api/v1/chapters").json()
    for chapter in body:
        assert chapter["engagement"] is None


# ---------------------------------------------------------------------------
# Chapter enum + ChapterStatus schema (the cross-repo contract)
# ---------------------------------------------------------------------------


def test_chapter_enum_is_exactly_the_six_codes_in_order():
    assert [c.value for c in Chapter] == [
        "school",
        "career",
        "family",
        "social",
        "travel",
        "culture",
    ]


def test_chapter_display_names_cover_all_six():
    assert {c: CHAPTER_DISPLAY_NAMES[c] for c in Chapter} == {
        Chapter.SCHOOL: "School",
        Chapter.CAREER: "Career",
        Chapter.FAMILY: "Family Life & Routine",
        Chapter.SOCIAL: "Social & Community",
        Chapter.TRAVEL: "Travel & Holiday",
        Chapter.CULTURE: "Culture & Faith",
    }


def test_chapter_status_serializes_chapter_as_the_string_code():
    # use_enum_values: the wire carries the plain code the app keys on, not the
    # Enum object. The not-started defaults are the baseline shape.
    status = ChapterStatus(chapter=Chapter.SCHOOL, display_name="School")
    dumped = status.model_dump()
    assert dumped == {
        "chapter": "school",
        "display_name": "School",
        "lci": None,
        "alert_level": None,
        "last_prepared_at": None,
        "activity_count": 0,
        "engagement": None,
    }


def test_chapter_status_accepts_filled_inputs_for_later_tasks():
    # When Tasks 5 to 7 land, a chapter can carry real inputs; the contract holds
    # the LCI as a float, the alert level as 1/2/3, a timestamp string, and a count.
    status = ChapterStatus(
        chapter=Chapter.SOCIAL,
        display_name="Social & Community",
        lci=42.0,
        alert_level=2,
        last_prepared_at="2026-06-11T10:00:00+00:00",
        activity_count=5,
    )
    dumped = status.model_dump()
    assert dumped["chapter"] == "social"
    assert dumped["lci"] == 42.0
    assert dumped["alert_level"] == 2
    assert dumped["last_prepared_at"] == "2026-06-11T10:00:00+00:00"
    assert dumped["activity_count"] == 5


def test_chapter_status_rejects_an_out_of_range_alert_level():
    # alert_level is constrained to 1, 2, or 3 (the three Erosion Alert levels).
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChapterStatus(chapter=Chapter.SCHOOL, display_name="School", alert_level=4)


def test_chapter_status_rejects_a_negative_activity_count():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChapterStatus(chapter=Chapter.SCHOOL, display_name="School", activity_count=-1)


# ---------------------------------------------------------------------------
# The engagement signal on the chapters service (owner-track Task 12, gated OFF)
# ---------------------------------------------------------------------------
#
# These drive list_chapter_statuses directly with the activity aggregates monkeypatched, so the
# engagement attachment is verified end-to-end (band -> governed copy -> wire) without coupling
# to the resolver's row-shape internals. The flag is the gate: OFF (default) attaches nothing.


@pytest.fixture
def stub_chapter_inputs(monkeypatch):
    """Stub the resolver + the three per-chapter inputs so a test controls the timestamps.

    Returns a setter the test calls with a {chapter_code: (count, last_prepared_at)} map; the
    LCI and alert reads are stubbed empty (this fixture is about the engagement signal, which
    is computed from the activity aggregates alone).
    """
    from app.services import chapters as chapters_service

    def set_inputs(aggregates):
        counts = {code: c for code, (c, _) in aggregates.items()}
        last_prepared = {code: ts for code, (_, ts) in aggregates.items() if ts is not None}
        monkeypatch.setattr(
            chapters_service, "resolve_child_id", lambda user, child_id=None: "ch-1"
        )
        monkeypatch.setattr(
            chapters_service,
            "_activity_aggregates_by_chapter",
            lambda user, cid: (counts, last_prepared),
        )
        monkeypatch.setattr(
            chapters_service.lci_service, "chapter_scores_by_code", lambda user, cid: {}
        )
        monkeypatch.setattr(
            chapters_service.alerts_service, "active_levels_by_chapter", lambda user, cid: {}
        )

    return set_inputs


def _by_code(statuses):
    return {s.chapter: s for s in statuses}


def _weeks_ago_iso(weeks):
    # A timestamp `weeks` weeks before the real now (the service bands against the live clock),
    # so these tests hold whatever day they run on.
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()


def test_engagement_is_omitted_when_the_flag_is_off(stub_chapter_inputs, monkeypatch):
    # The DEFAULT: the flag is off, so even a long-quiet chapter carries no engagement copy (the
    # surface is gated on the Task-12 psychiatrist sign-off). A chapter last prepared 20 weeks
    # ago WOULD be "resting" if the flag were on; with it off, engagement is None.
    from app.services import chapters as chapters_service

    monkeypatch.delenv("ENGAGEMENT_SIGNAL_ENABLED", raising=False)
    stub_chapter_inputs({"travel": (3, _weeks_ago_iso(20))})
    statuses = chapters_service.list_chapter_statuses(AUTHED)
    for status in statuses:
        assert status.engagement is None


def test_engagement_surfaces_resting_for_a_long_quiet_chapter_when_enabled(
    stub_chapter_inputs, monkeypatch
):
    # Flag ON: a once-active chapter last prepared 20 weeks ago surfaces the governed RESTING
    # signal (band code, the "Resting" label, a factual note, a warm invitation). The app
    # renders this verbatim. 20 weeks is well past the 8-week resting threshold.
    from app.services import chapters as chapters_service

    monkeypatch.setenv("ENGAGEMENT_SIGNAL_ENABLED", "1")
    stub_chapter_inputs({"travel": (3, _weeks_ago_iso(20))})
    travel = _by_code(chapters_service.list_chapter_statuses(AUTHED))[Chapter.TRAVEL.value]
    assert travel.engagement is not None
    assert travel.engagement.band == "resting"
    assert travel.engagement.label == "Resting"
    assert travel.engagement.note  # a factual line about the plan record
    assert travel.engagement.invitation  # a warm forward door


def test_engagement_is_none_for_a_never_started_chapter_even_when_enabled(
    stub_chapter_inputs, monkeypatch
):
    # The was-active-then-quiet guard end-to-end: a chapter with ZERO activity is the existing
    # not-started, never quiet/resting, even with the flag ON. You cannot abandon what you never
    # began. (This is the app-visible proof the guard holds through the service + model.)
    from app.services import chapters as chapters_service

    monkeypatch.setenv("ENGAGEMENT_SIGNAL_ENABLED", "1")
    stub_chapter_inputs({"travel": (0, None)})
    travel = _by_code(chapters_service.list_chapter_statuses(AUTHED))[Chapter.TRAVEL.value]
    assert travel.engagement is None


def test_engagement_is_none_for_a_recently_prepared_chapter_when_enabled(
    stub_chapter_inputs, monkeypatch
):
    # A healthy, recently-prepared chapter (within 4 weeks) is ACTIVE, which surfaces no copy:
    # the signal only ever shows for a chapter that has gone quiet, never for an active one.
    from app.services import chapters as chapters_service

    monkeypatch.setenv("ENGAGEMENT_SIGNAL_ENABLED", "1")
    stub_chapter_inputs({"travel": (2, _weeks_ago_iso(1))})  # prepared a week ago: ACTIVE
    travel = _by_code(chapters_service.list_chapter_statuses(AUTHED))[Chapter.TRAVEL.value]
    assert travel.engagement is None
