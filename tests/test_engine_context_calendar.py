"""Tests for the calendar reference data + the PURE context builder (Part B, calendar slice).

The display-only calendar context (FeatureDecisions.md 2026-06-19) selects PUBLIC calendar
windows that overlap a date range and renders each as a governed world-fact. These tests pin:
  - the reference data is well-formed (start <= end; bank holidays exact; the honesty
    confidence labels: bank holidays "confirmed", school holidays "approximate");
  - windows_overlapping is inclusive, returns only overlapping windows, sorted by date;
  - resolve_range defaults to a bounded look-back, normalises a reversed range, and CLAMPS
    the span (the every-list-is-capped posture);
  - build_calendar_context is DETERMINISTIC and SYMMETRIC by construction: it takes only a
    date range (no score), so it annotates a good stretch exactly as a quiet one.

No Supabase and no clock: `today` is passed in, so the builder is a pure function.
"""

from __future__ import annotations

from datetime import date

from app.engines.context import (
    COVERAGE_YEARS,
    DEFAULT_LOOKBACK_DAYS,
    MAX_RANGE_DAYS,
    all_windows,
    build_calendar_context,
    find_prohibited_words,
    resolve_range,
    windows_overlapping,
)


def _labels(windows):
    return [w.label for w in windows]


# ---------------------------------------------------------------------------
# the reference data is well-formed
# ---------------------------------------------------------------------------


def test_every_window_start_is_on_or_before_its_end():
    for w in all_windows():
        assert w.start <= w.end, w


def test_coverage_years_are_2025_and_2026():
    assert COVERAGE_YEARS == (2025, 2026)
    for w in all_windows():
        assert w.start.year in COVERAGE_YEARS or w.end.year in COVERAGE_YEARS, w


def test_bank_holidays_are_exact_and_confirmed():
    by_key = {(w.label, w.start) for w in all_windows() if w.kind == "bank_holiday"}
    # Spot-checks against the GOV.UK England & Wales list.
    assert ("Spring bank holiday", date(2025, 5, 26)) in by_key
    assert ("Christmas Day", date(2025, 12, 25)) in by_key
    assert ("Good Friday", date(2026, 4, 3)) in by_key
    # 26 Dec 2026 is a Saturday, so the Boxing Day bank holiday is the Monday substitute.
    assert ("Boxing Day (substitute day)", date(2026, 12, 28)) in by_key
    for w in all_windows():
        if w.kind == "bank_holiday":
            assert w.confidence == "confirmed"
            assert w.start == w.end  # a single-day holiday


def test_school_holidays_are_labelled_approximate():
    school = [w for w in all_windows() if w.kind == "school_holiday"]
    assert school, "expected school-holiday windows"
    for w in school:
        assert w.confidence == "approximate"
        assert "approximate" in w.source.lower()


# ---------------------------------------------------------------------------
# windows_overlapping: inclusive, only-overlapping, sorted
# ---------------------------------------------------------------------------


def test_overlap_is_inclusive_on_both_edges():
    windows = all_windows()
    # A single-day range exactly on the Spring 2025 bank holiday includes it.
    on_day = windows_overlapping(windows, date(2025, 5, 26), date(2025, 5, 26))
    assert ("Spring bank holiday", date(2025, 5, 26)) in {(w.label, w.start) for w in on_day}
    # The day AFTER it does not (the bank holiday is a single day).
    after = windows_overlapping(windows, date(2025, 5, 27), date(2025, 5, 27))
    assert "Spring bank holiday" not in _labels(
        [w for w in after if w.start == date(2025, 5, 26)]
    )


def test_overlap_returns_only_overlapping_windows_sorted_by_start():
    # July to August 2025 overlaps the summer holidays + the summer bank holiday, not
    # Christmas.
    hits = windows_overlapping(all_windows(), date(2025, 7, 1), date(2025, 8, 31))
    labels = _labels(hits)
    assert "Summer holidays" in labels
    assert "Summer bank holiday" in labels
    assert "Christmas holidays" not in labels
    # Sorted ascending by start date.
    assert hits == sorted(hits, key=lambda w: (w.start, w.end, w.label))


# ---------------------------------------------------------------------------
# resolve_range: defaults, normalisation, clamp
# ---------------------------------------------------------------------------


def test_resolve_range_defaults_to_the_bounded_lookback():
    today = date(2026, 6, 19)
    start, end = resolve_range(today, None, None)
    assert end == today
    assert (end - start).days == DEFAULT_LOOKBACK_DAYS


def test_resolve_range_normalises_a_reversed_range():
    today = date(2026, 6, 19)
    start, end = resolve_range(today, date(2026, 6, 1), date(2025, 1, 1))
    assert start == date(2025, 1, 1)
    assert end == date(2026, 6, 1)
    assert start < end


def test_resolve_range_clamps_an_oversized_span():
    today = date(2026, 6, 19)
    start, end = resolve_range(today, date(2000, 1, 1), date(2026, 6, 19))
    assert end == date(2026, 6, 19)
    assert (end - start).days == MAX_RANGE_DAYS


# ---------------------------------------------------------------------------
# build_calendar_context: deterministic, symmetric, governed
# ---------------------------------------------------------------------------


def test_build_is_deterministic():
    a = build_calendar_context(date(2026, 6, 19), date(2025, 1, 1), date(2025, 12, 31))
    b = build_calendar_context(date(2026, 6, 19), date(2025, 1, 1), date(2025, 12, 31))
    assert [(w.window.label, w.window.start, w.note) for w in a.windows] == [
        (w.window.label, w.window.start, w.note) for w in b.windows
    ]
    assert (a.from_date, a.to_date) == (b.from_date, b.to_date)


def test_build_notes_are_all_clean():
    ctx = build_calendar_context(date(2026, 6, 19), date(2025, 1, 1), date(2026, 12, 31))
    for rendered in ctx.windows:
        assert find_prohibited_words(rendered.note) == [], rendered.note


def test_build_selects_by_date_only_so_it_is_symmetric():
    # The builder takes ONLY a date range: there is no score parameter, so it cannot soften a
    # decline. A summer window returns the same windows regardless of anything else.
    ctx = build_calendar_context(date(2026, 6, 19), date(2025, 7, 1), date(2025, 8, 31))
    labels = [w.window.label for w in ctx.windows]
    assert "Summer holidays" in labels
    assert "Summer bank holiday" in labels
    assert ctx.from_date == date(2025, 7, 1)
    assert ctx.to_date == date(2025, 8, 31)
