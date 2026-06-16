"""GOVERNED COPY for the per-chapter ENGAGEMENT signal.

The engagement signal (the owner's "disengagement" Tier-1 idea, owner-track Task 12; the
researcher + psychiatrist boards' HONEST shape) shows, on a chapter's OWN card, a calm band
("Quiet" / "Resting") when that chapter has gone a while without a prepared plan. The band is
computed deterministically in bands.py; THIS module holds the warm, factual strings the band
maps to. Every string is GOVERNED: it states a fact about the PLAN RECORD, never makes the
carer the subject of a failure, carries NO count / streak / trend, and offers a warm forward
invitation. It is the analogue of app/engines/alerts/copy.py and app/engines/checkin/copy.py.

How the boards' conditions land in this copy:
  - FACTUAL about the plan, not a verdict on the carer. "No plan prepared here in over 8
    weeks", NEVER "you haven't prepared" / "you let this slip". The carer is never the
    subject of a failure sentence (Psychiatrist.md: a population that under-asks must not be
    shamed; historyPresentation.ts: factual, not a verdict).
  - WARM forward invitation, always. "Want to prepare for something?", "Here whenever you're
    ready." The signal opens a door, it never scolds.
  - NO count / streak / trend on the gap. The copy never says "3 weeks in a row", "down from
    last month", or a number of times: those are the deficit / comparison mechanics the
    boards rejected. The band ("Quiet" / "Resting") is the only granularity shown.
  - The labels are "Quiet" / "Resting" / "No recent plan" (and "Not started" for the existing
    grey baseline). The words "Dormant" and "Abandoned" are BANNED and never appear in any
    user-facing string (the guard enforces it).

Every string here passes the engagement guard (app/engines/engagement/guard.py): render_signal
re-checks at emit time and the guard test (tests/test_engine_engagement_guard.py) pins it over
ALL copy (clinical AND shame / deficit / streak words).

This module holds STRINGS only. The flag that decides WHETHER this signal is enabled for real
users lives in app/engines/engagement/flag.py (OFF by default until sign-off); the chapters
service (app/services/chapters.py) attaches the rendered signal to each ChapterStatus when the
flag is on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.engines.engagement.bands import ACTIVE_MAX_WEEKS, QUIET_MAX_WEEKS, EngagementBand
from app.engines.engagement.guard import assert_clean


@dataclass(frozen=True)
class EngagementContent:
    """The governed, rendered engagement signal for one band (what the app shows verbatim).

    label is the short status word ("Quiet" / "Resting"); note is the FACTUAL one-line
    statement about the plan record (never the carer as the subject of a failure); invitation
    is the warm forward door. This is what ChapterStatus.engagement serializes; the app renders
    it verbatim and authors no wording. A band with no surfaced signal (NOT_STARTED, ACTIVE)
    returns None from render_signal, so the card shows nothing extra.
    """

    band: EngagementBand
    label: str
    note: str
    invitation: str


# --- the short status labels (the boards' approved words) ---------------------
# "Quiet" / "Resting" for the two once-active gaps, "No recent plan" as the neutral header
# word, and "Not started" for the existing grey baseline. NEVER "Dormant" or "Abandoned"
# (banned by the guard). NOT_STARTED and ACTIVE carry a label for completeness, but
# render_signal does not surface a signal for them.
_LABELS: Dict[EngagementBand, str] = {
    EngagementBand.NOT_STARTED: "Not started",
    EngagementBand.ACTIVE: "Recently prepared",
    EngagementBand.QUIET: "Quiet",
    EngagementBand.RESTING: "Resting",
}

# --- the factual notes about the PLAN RECORD (never the carer) ----------------
# Each states a fact about how long it has been since a plan was prepared HERE, with the
# chapter as the subject, never the carer. No count, no streak, no comparison. The week
# thresholds are interpolated from the band constants so the copy and the bands never disagree.
_NOTES: Dict[EngagementBand, str] = {
    EngagementBand.QUIET: (
        f"No plan prepared here in over {ACTIVE_MAX_WEEKS} weeks. "
        "That is completely okay."
    ),
    EngagementBand.RESTING: (
        f"No recent plan in this chapter for over {QUIET_MAX_WEEKS} weeks. "
        "This chapter is just resting."
    ),
}

# --- the warm forward invitations (a door, never a scold) ---------------------
_INVITATIONS: Dict[EngagementBand, str] = {
    EngagementBand.QUIET: "Want to prepare for something?",
    EngagementBand.RESTING: "Here whenever you're ready.",
}

# The bands that surface a signal on the card. NOT_STARTED keeps its existing grey state and
# ACTIVE is the healthy default, so neither adds copy: only QUIET and RESTING do.
_SURFACED_BANDS = (EngagementBand.QUIET, EngagementBand.RESTING)


def label_for(band: EngagementBand) -> str:
    """The short status word for a band ("Quiet" / "Resting" / ...). Never Dormant/Abandoned."""
    return _LABELS[band]


def render_signal(band: EngagementBand) -> Optional[EngagementContent]:
    """Build the governed EngagementContent for a band, or None when nothing is surfaced.

    Surfaces a signal ONLY for QUIET and RESTING (a once-active chapter that has gone a while
    without a plan); NOT_STARTED (the existing grey baseline) and ACTIVE (healthy) return None,
    so the card shows no extra engagement copy. For a surfaced band it resolves the label, the
    factual note, and the warm invitation, then runs the guard over EVERY emitted string so a
    prohibited clinical OR shame / deficit / streak word can never leave the engine.
    """
    if band not in _SURFACED_BANDS:
        return None
    label = label_for(band)
    note = _NOTES[band]
    invitation = _INVITATIONS[band]

    assert_clean(label, note, invitation)

    return EngagementContent(band=band, label=label, note=note, invitation=invitation)


def all_emitted_strings() -> List[str]:
    """Every governed string the engagement signal can emit, across all bands.

    The guard test iterates this to assert NO prohibited word (clinical OR shame / deficit /
    streak) appears anywhere: every band label, and the note + invitation of every surfaced
    band. Keeping the enumeration here (next to the copy) means a new band or string is covered
    by the test automatically.
    """
    strings: List[str] = list(_LABELS.values())
    for band in _SURFACED_BANDS:
        strings.append(_NOTES[band])
        strings.append(_INVITATIONS[band])
    return strings
