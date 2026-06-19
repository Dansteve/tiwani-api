"""The static UK calendar reference for the display-only context layer (v1).

PUBLIC reference data only, never personal data: UK bank holidays (exact, GOV.UK Bank
Holidays, Open Government Licence) and school-holiday periods (approximate, England
state schools). The context layer overlays these dates on the check-in history so a
Coordinator can SEE, for themselves, that a quiet stretch fell over (say) the summer
holidays: the "seasonal pause vs real narrowing" call the panel approved
(FeatureDecisions.md 2026-06-19, the Real-World Context Layer Part B). It is
WORLD-FACTS only: a date is a date. This module makes NO claim about a score, and the
determinism firewall keeps it out of the LCE/LCI/Alerts entirely.

PROVENANCE + CONFIDENCE (the panel's honesty condition): every window carries its
source and a qualitative confidence, never a decimal. Bank holidays are CONFIRMED (the
GOV.UK list); school holidays are APPROXIMATE (term dates vary by local authority and
academy), so they are a labelled England-state-school approximation, never presented as
exact. Coverage is 2025 to 2026; extend by adding rows, never by inferring dates.

This is the bare reference set, intentionally small. Nation-awareness (Scotland / NI
divisions) and live GOV.UK / per-LA term fetching are the larger, separate, DPIA-gated
epic (the location-bearing sources), not this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Tuple

from typing_extensions import Literal

WindowKind = Literal["bank_holiday", "school_holiday"]
Confidence = Literal["confirmed", "approximate"]

# Provenance strings, carried on every window for the honesty condition.
SOURCE_BANK_HOLIDAYS = "GOV.UK Bank Holidays (Open Government Licence)"
SOURCE_SCHOOL_HOLIDAYS = "England school holidays (approximate)"

DIVISION_ENGLAND_AND_WALES = "england-and-wales"
DIVISION_ENGLAND = "england"

# The coverage years, stated so a caller knows the bounds: a date outside is simply
# un-annotated, never guessed.
COVERAGE_YEARS: Tuple[int, ...] = (2025, 2026)


@dataclass(frozen=True)
class CalendarWindow:
    """One public calendar window (a bank-holiday day, or a school-holiday period).

    A WORLD-FACT: a labelled date span with its source and a qualitative confidence.
    `start` and `end` are INCLUSIVE dates (a single-day bank holiday has start == end).
    It carries NO score and NO interpretation: the governed copy (copy.py) renders the
    factual note, and the Coordinator draws their own conclusion.
    """

    kind: WindowKind
    label: str
    start: date
    end: date
    division: str
    source: str
    confidence: Confidence


def _bh(label: str, day: date) -> CalendarWindow:
    return CalendarWindow(
        kind="bank_holiday",
        label=label,
        start=day,
        end=day,
        division=DIVISION_ENGLAND_AND_WALES,
        source=SOURCE_BANK_HOLIDAYS,
        confidence="confirmed",
    )


def _school(label: str, start: date, end: date) -> CalendarWindow:
    return CalendarWindow(
        kind="school_holiday",
        label=label,
        start=start,
        end=end,
        division=DIVISION_ENGLAND,
        source=SOURCE_SCHOOL_HOLIDAYS,
        confidence="approximate",
    )


# England & Wales bank holidays, 2025 + 2026 (GOV.UK Bank Holidays, OGL). CONFIRMED.
_BANK_HOLIDAYS: Tuple[CalendarWindow, ...] = (
    _bh("New Year's Day", date(2025, 1, 1)),
    _bh("Good Friday", date(2025, 4, 18)),
    _bh("Easter Monday", date(2025, 4, 21)),
    _bh("Early May bank holiday", date(2025, 5, 5)),
    _bh("Spring bank holiday", date(2025, 5, 26)),
    _bh("Summer bank holiday", date(2025, 8, 25)),
    _bh("Christmas Day", date(2025, 12, 25)),
    _bh("Boxing Day", date(2025, 12, 26)),
    _bh("New Year's Day", date(2026, 1, 1)),
    _bh("Good Friday", date(2026, 4, 3)),
    _bh("Easter Monday", date(2026, 4, 6)),
    _bh("Early May bank holiday", date(2026, 5, 4)),
    _bh("Spring bank holiday", date(2026, 5, 25)),
    _bh("Summer bank holiday", date(2026, 8, 31)),
    _bh("Christmas Day", date(2026, 12, 25)),
    _bh("Boxing Day (substitute day)", date(2026, 12, 28)),
)

# England school-holiday periods, 2025 + 2026. APPROXIMATE (term dates vary by local
# authority + academy): a labelled England-state-school approximation, never exact.
_SCHOOL_HOLIDAYS: Tuple[CalendarWindow, ...] = (
    _school("Spring half-term", date(2025, 2, 17), date(2025, 2, 21)),
    _school("Easter holidays", date(2025, 4, 7), date(2025, 4, 21)),
    _school("Summer half-term", date(2025, 5, 26), date(2025, 5, 30)),
    _school("Summer holidays", date(2025, 7, 23), date(2025, 9, 1)),
    _school("Autumn half-term", date(2025, 10, 27), date(2025, 10, 31)),
    _school("Christmas holidays", date(2025, 12, 22), date(2026, 1, 2)),
    _school("Spring half-term", date(2026, 2, 16), date(2026, 2, 20)),
    _school("Easter holidays", date(2026, 3, 30), date(2026, 4, 10)),
    _school("Summer half-term", date(2026, 5, 25), date(2026, 5, 29)),
    _school("Summer holidays", date(2026, 7, 22), date(2026, 9, 1)),
    _school("Autumn half-term", date(2026, 10, 26), date(2026, 10, 30)),
)

ALL_WINDOWS: Tuple[CalendarWindow, ...] = _BANK_HOLIDAYS + _SCHOOL_HOLIDAYS


def all_windows() -> List[CalendarWindow]:
    """Every calendar window in the reference set (bank holidays + school holidays)."""
    return list(ALL_WINDOWS)
