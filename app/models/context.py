"""Calendar context pydantic schemas: the display-only Real-World Context Layer read.

The cross-repo contract for the calendar context (FeatureDecisions.md 2026-06-19, the
Real-World Context Layer Part B). The app mirrors CalendarContextResponse field-for-field
and renders the api's VERBATIM governed copy (it authors no wording, exactly as it renders
alerts); the api is the authoritative schema and the only source of the copy.

This surface reads NO personal data: the calendar is PUBLIC reference data (UK bank
holidays + England school-holiday periods). It carries NO score and NO trajectory: the app
overlays these windows on the check-in history it already has, so a Coordinator can see a
quiet stretch fell over (say) the holidays and judge it for themselves. The determinism
firewall keeps these dates out of the LCE/LCI/Alerts entirely.

  - CalendarWindowView: one public calendar window {kind, label, start, end, division,
    note, source, confidence}. `note` is the governed world-fact string; `confidence` is a
    qualitative label ("confirmed" for bank holidays, "approximate" for school holidays),
    never a decimal (the panel's honesty condition).
  - CalendarContextResponse: the GET /api/v1/context/calendar response {from_date, to_date,
    intro, hedge, windows, needs_signoff}. `intro` + `hedge` are the always-shown governed
    strings; `needs_signoff` is a constant reminder this surface is sign-off gated.
"""

from __future__ import annotations

from datetime import date
from typing import List

from pydantic import BaseModel
from typing_extensions import Literal

# The window kind + the qualitative confidence on the wire (never a numeric score/decimal).
WindowKindCode = Literal["bank_holiday", "school_holiday"]
ConfidenceCode = Literal["confirmed", "approximate"]


class CalendarWindowView(BaseModel):
    """One public calendar window as the app renders it (a world-fact, never a verdict).

    `kind` is bank_holiday or school_holiday; `label` + `note` are the governed strings the
    app shows verbatim; `start` / `end` are inclusive ISO dates; `division` names the area
    the window applies to; `source` + `confidence` carry the provenance the app surfaces so
    the user knows how solid the date is (bank holidays confirmed, school holidays
    approximate).
    """

    kind: WindowKindCode
    label: str
    start: date
    end: date
    division: str
    note: str
    source: str
    confidence: ConfidenceCode


class CalendarContextResponse(BaseModel):
    """The display-only calendar context as the app renders it (Part B, calendar slice).

    Mirrored by the app field-for-field. `intro` + `hedge` are the VERBATIM governed text
    (the app never paraphrases); `windows` are the public dates overlapping the resolved
    [from_date, to_date] range, in date order. `needs_signoff` is always true: a standing
    reminder this surface is gated on the psychiatrist copy sign-off (the route only serves
    it when the OFF-by-default flag is enabled). Nothing here is derived from a score: the
    calendar never touches the LCE/LCI/Alerts.
    """

    from_date: date
    to_date: date
    intro: str
    hedge: str
    windows: List[CalendarWindowView]
    needs_signoff: bool = True
