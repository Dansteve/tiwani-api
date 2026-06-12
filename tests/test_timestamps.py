"""The shared Supabase timestamptz parser (app/services/timestamps.py).

Pins the bug that 500'd the Card History: PostgREST returns the Postgres text form with a
SPACE separator and an HOURS-ONLY offset ("...+00"), which Python 3.9's bare fromisoformat
rejects, so the old per-service _parse_dt returned None and CardSummary.created_at blew up.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.timestamps import parse_timestamptz


def test_parses_the_live_postgrest_hours_only_offset():
    # The exact shape PostgREST returns for a timestamptz on the live DB.
    dt = parse_timestamptz("2026-06-11 18:31:06.314261+00")
    assert dt == datetime(2026, 6, 11, 18, 31, 6, 314261, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value,expected",
    [
        (
            "2026-06-11T18:31:06.314261+00:00",
            datetime(2026, 6, 11, 18, 31, 6, 314261, tzinfo=timezone.utc),
        ),
        ("2026-06-11T18:31:06Z", datetime(2026, 6, 11, 18, 31, 6, tzinfo=timezone.utc)),
        (
            "2026-06-11 18:31:06+0530",
            datetime(2026, 6, 11, 18, 31, 6, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        ),
        (None, None),
    ],
)
def test_parses_the_other_shapes(value, expected):
    assert parse_timestamptz(value) == expected


def test_naive_string_is_assumed_utc():
    parsed = parse_timestamptz("2026-06-11T18:31:06.123")
    assert parsed is not None and parsed.tzinfo == timezone.utc


def test_datetime_passthrough_and_unparseable_is_none():
    aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert parse_timestamptz(aware) is aware
    assert parse_timestamptz("not-a-date") is None
