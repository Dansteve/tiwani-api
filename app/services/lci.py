"""Life Continuity Index data + read service (v3).

The layer between the LCI routes (and the post-pulse recompute) and Supabase. It
fetches the user's stored pulses and LCI snapshots, calls the PURE index engine
(app/engines/lci) to compute the chapter and overall scores, the trajectories, and
the sparse labels, and shapes the ChapterLci / OverallLci the app renders. It also
writes an lci_snapshot when a chapter's score changes (after a pulse). No index math
lives here; the engine owns the formula (section 4.8, AUTHORITATIVE).

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every read and
write runs through get_anon_client(user.access_token), so Row Level Security scopes
every pulse and snapshot to the caller. The six chapters are the fixed Chapter set.

The trajectory (section 4.8) compares the current score to the score 7 days prior,
read from the latest lci_snapshot at or before (now - 7 days). When no snapshot is
that old yet, the chapter reads "building your picture" (not enough data).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.lci import (
    Outcome,
    PulsePoint,
    Snapshot,
    chapter_score,
    label_for,
    overall_score,
    prior_instant,
    snapshot_score_as_of,
    trajectory,
)
from app.models.chapters_v3 import Chapter
from app.models.lci import ChapterLci, OverallLci
from app.models.seed import Tier
from app.services.profile import _rows

PULSE_RECORD_TABLE = "pulse_record"
LCI_SNAPSHOT_TABLE = "lci_snapshot"


# ---------------------------------------------------------------------------
# reads (the dashboard + the LCI endpoints)
# ---------------------------------------------------------------------------


def chapter_lci_list(user: AuthedUser, *, now: Optional[datetime] = None) -> List[ChapterLci]:
    """The per-chapter LCI for the user: one ChapterLci per fixed Life Chapter.

    Reads all the user's pulses (grouped by chapter) and all their snapshots once,
    then for each of the six chapters computes the current score (engine fold), the
    pulse count, the trajectory vs the 7-days-prior snapshot, and the sparse label.
    A chapter with no pulse is score=null, pulse_count=0, label "--", trajectory
    building_picture. Always returns all six in the stable Chapter order.
    """
    base_now = _utc_now(now)
    pulses_by_chapter = _pulses_by_chapter(user)
    snapshots_by_chapter = _snapshots_by_chapter(user)
    look_back = prior_instant(base_now)

    out: List[ChapterLci] = []
    for chapter in Chapter:
        pulses = pulses_by_chapter.get(chapter.value, [])
        score = chapter_score(pulses)
        pulse_count = len(pulses)
        prior = snapshot_score_as_of(snapshots_by_chapter.get(chapter.value, []), look_back)
        out.append(
            ChapterLci(
                chapter=chapter,
                score=score,
                trajectory=trajectory(score, prior),
                pulse_count=pulse_count,
                label=label_for(pulse_count),
                timestamp=base_now,
            )
        )
    return out


def overall_lci(user: AuthedUser, *, now: Optional[datetime] = None) -> OverallLci:
    """The overall LCI for the user: the equal-weighted mean of chapters with a pulse.

    Builds the per-chapter list, takes the mean of the chapters that have a score
    (no-data chapters excluded, never zero), and derives the overall trajectory by
    comparing the current overall to the overall reconstructed from the 7-days-prior
    snapshots (the same look-back instant for every chapter). chapters_included lists
    the chapters that contributed. The overall label uses the total pulse count
    across the included chapters (sparse while fewer than 3 pulses exist anywhere).
    """
    base_now = _utc_now(now)
    chapters = chapter_lci_list(user, now=base_now)

    included = [c for c in chapters if c.score is not None]
    current = overall_score([c.score for c in chapters])

    prior = _overall_prior(user, base_now)
    total_pulses = sum(c.pulse_count for c in included)

    return OverallLci(
        score=current,
        trajectory=trajectory(current, prior),
        chapters_included=[Chapter(c.chapter) for c in included],
        label=label_for(total_pulses),
        timestamp=base_now,
    )


def _overall_prior(user: AuthedUser, now: datetime) -> Optional[int]:
    """The overall score 7 days prior, from each chapter's latest old-enough snapshot.

    For the overall trajectory: take each chapter's snapshot score at or before
    (now - 7 days) and average the ones that exist, the same equal-weighted mean the
    current overall uses. None when no chapter has a 7-days-prior snapshot yet (the
    overall then reads building_picture).
    """
    look_back = prior_instant(now)
    snapshots_by_chapter = _snapshots_by_chapter(user)
    prior_scores = [
        snapshot_score_as_of(snaps, look_back) for snaps in snapshots_by_chapter.values()
    ]
    return overall_score(prior_scores)


# ---------------------------------------------------------------------------
# write (the post-pulse recompute, called from the Pulse service)
# ---------------------------------------------------------------------------


def recompute_chapter_lci(user: AuthedUser, chapter: str, *, now: Optional[datetime] = None) -> int:
    """Recompute a chapter's LCI from its pulses and record a fresh snapshot.

    Called after a Pulse is recorded (section 4.7 step 2, within 10 seconds): re-folds
    the chapter's full pulse history into the current score (section 4.8) and inserts
    an lci_snapshot row capturing it, so the weekly trajectory and the Task 7
    "declining 3 snapshots" rule have the point. Returns the new chapter score (always
    a value: the recompute runs only after a pulse exists for the chapter). The fold
    is over the stored outcomes and the stored recommended tiers, never a re-derived
    tier.
    """
    base_now = _utc_now(now)
    pulses = _pulses_by_chapter(user).get(chapter, [])
    score = chapter_score(pulses)
    if score is None:
        # Defensive: the recompute is only triggered after a pulse is written, so the
        # chapter always has at least one. If it somehow has none, there is nothing to
        # snapshot; start at the engine's starting value is not appropriate (no pulse),
        # so report the floor without writing a snapshot.
        return 0
    _insert_snapshot(user, chapter=chapter, score=score, taken_at=base_now)
    return score


def _insert_snapshot(user: AuthedUser, *, chapter: str, score: int, taken_at: datetime) -> None:
    """Insert one lci_snapshot row (user-scoped) capturing a chapter's score now."""
    client = get_anon_client(user.access_token)
    client.table(LCI_SNAPSHOT_TABLE).insert(
        {
            "user_id": user.id,
            "chapter": chapter,
            "score": score,
            "taken_at": taken_at.isoformat(),
        }
    ).execute()


# ---------------------------------------------------------------------------
# fetch + map (stored rows -> the engine's pure inputs)
# ---------------------------------------------------------------------------


def _pulses_by_chapter(user: AuthedUser) -> Dict[str, List[PulsePoint]]:
    """The user's pulses as engine PulsePoints, grouped by chapter code.

    Reads every pulse_record for the user under RLS (outcome, tier, chapter,
    created_at) and maps each to the minimal triple the index folds. A row with an
    unparseable outcome or tier is skipped (the column CHECKs make that unreachable
    in practice; the guard keeps a bad row from breaking the whole dashboard).
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE)
        .select("chapter, outcome_code, tier_recommended, created_at")
        .eq("user_id", user.id)
        .execute()
    )

    grouped: Dict[str, List[PulsePoint]] = defaultdict(list)
    for row in rows:
        point = _to_pulse_point(row)
        if point is None:
            continue
        chapter = row.get("chapter")
        if chapter is None:
            continue
        grouped[chapter].append(point)
    return grouped


def _to_pulse_point(row: Dict[str, Any]) -> Optional[PulsePoint]:
    """Map a pulse_record row to a PulsePoint, or None if its codes do not parse."""
    try:
        outcome = Outcome(row.get("outcome_code"))
        tier = Tier(row.get("tier_recommended"))
    except ValueError:
        return None
    at = _parse_dt(row.get("created_at"))
    if at is None:
        return None
    return PulsePoint(outcome=outcome, tier=tier, at=at)


def _snapshots_by_chapter(user: AuthedUser) -> Dict[str, List[Snapshot]]:
    """The user's LCI snapshots as engine Snapshots, grouped by chapter code."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(LCI_SNAPSHOT_TABLE)
        .select("chapter, score, taken_at")
        .eq("user_id", user.id)
        .execute()
    )

    grouped: Dict[str, List[Snapshot]] = defaultdict(list)
    for row in rows:
        chapter = row.get("chapter")
        taken_at = _parse_dt(row.get("taken_at"))
        score = row.get("score")
        if chapter is None or taken_at is None or score is None:
            continue
        grouped[chapter].append(Snapshot(score=int(score), taken_at=taken_at))
    return grouped


def chapter_scores_by_code(user: AuthedUser) -> Dict[str, Optional[int]]:
    """The current LCI per chapter code (for the dashboard wiring, ChapterStatus.lci).

    A thin helper the chapters dashboard service calls: maps each chapter code to its
    current score (None for a chapter with no pulse). Only chapters with a pulse get a
    value; the rest are absent (the caller defaults them to null). Reuses the same
    pulse fold as the LCI endpoints, so the dashboard and the LCI dashboard agree.
    """
    pulses_by_chapter = _pulses_by_chapter(user)
    return {code: chapter_score(pulses) for code, pulses in pulses_by_chapter.items()}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _utc_now(now: Optional[datetime]) -> datetime:
    """The clock for the read/recompute, injectable for tests; defaults to UTC now."""
    if now is not None:
        return now
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a timestamptz value (ISO string or datetime) to an aware datetime.

    Supabase returns timestamps as ISO-8601 strings; the fakes may pass a datetime
    directly. A naive value is treated as UTC so comparisons against the aware `now`
    never raise. Returns None for an unparseable value.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None
