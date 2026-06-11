"""No-DB tests for the v3 six-chapter dashboard endpoint and its schema.

The route tests drive the real FastAPI app (main.app) through a TestClient. Auth
is the only seam: the current-user dependency is overridden with a fixed
AuthedUser for the authenticated case, and left real for the 401 case (a missing
token short-circuits the dependency before any Supabase call). The chapters
service needs no Supabase mock: for a fresh user it reads nothing and builds the
six-chapter baseline from the fixed Chapter enum, so these run with no live
Supabase (blocked in the sandbox; the task requires mocking).

They pin the cross-repo contract for GET /api/v3/chapters: auth required (401),
exactly the six chapters in a stable order, all null/0 for a fresh user, and the
correct codes + display names. The schema tests pin the ChapterStatus shape and
the code/name mapping the app mirrors exactly.
"""

import pytest

from app.auth import AuthedUser, get_current_user
from app.models.chapters_v3 import (
    CHAPTER_DISPLAY_NAMES,
    Chapter,
    ChapterStatus,
)

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
def authed(client):
    """Override the current-user dependency with a fixed authed user."""
    client.app.dependency_overrides[get_current_user] = lambda: AUTHED
    yield client
    client.app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# auth required (401): real dependency, no token
# ---------------------------------------------------------------------------


def test_chapters_requires_authentication(client):
    # No Authorization header => the current-user dependency raises 401 before any
    # Supabase call (it short-circuits on missing credentials).
    response = client.get("/api/v3/chapters")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v3/chapters (fresh user)
# ---------------------------------------------------------------------------


def test_chapters_returns_exactly_six(authed):
    response = authed.get("/api/v3/chapters")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 6


def test_chapters_are_in_stable_order_with_correct_codes_and_names(authed):
    body = authed.get("/api/v3/chapters").json()
    assert [(c["chapter"], c["display_name"]) for c in body] == EXPECTED_CHAPTERS


def test_chapters_are_all_not_started_for_a_fresh_user(authed):
    # A fresh user has no activities, LCI, or alerts yet (Tasks 5 to 7), so every
    # chapter is the "not started" baseline: lci/alert_level/last_prepared_at null
    # and activity_count 0. The api returns raw inputs only; the app maps these to
    # grey per section 4.3 (the api never sends a colour).
    body = authed.get("/api/v3/chapters").json()
    for chapter in body:
        assert chapter["lci"] is None
        assert chapter["alert_level"] is None
        assert chapter["last_prepared_at"] is None
        assert chapter["activity_count"] == 0


def test_chapters_payload_carries_exactly_the_contract_fields(authed):
    body = authed.get("/api/v3/chapters").json()
    expected_keys = {
        "chapter",
        "display_name",
        "lci",
        "alert_level",
        "last_prepared_at",
        "activity_count",
    }
    for chapter in body:
        assert set(chapter.keys()) == expected_keys


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
