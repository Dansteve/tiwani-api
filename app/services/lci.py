"""Life Continuity Index data + read service (v3).

The layer between the LCI routes (and the post-pulse recompute) and Supabase. It
fetches the user's stored pulses and LCI snapshots, calls the PURE index engine
(app/engines/lci) to compute the chapter and overall scores, the trajectories, and
the sparse labels, and shapes the ChapterLci / OverallLci the app renders. It also
writes an lci_snapshot when a chapter's score changes (after a pulse). No index math
lives here; the engine owns the formula (section 4.8, AUTHORITATIVE).

User + recipient scoping and RLS (Auth.md, Models.md; Docs/FeatureDecisions.md, the
multi care recipient design note): every read and write runs through
get_anon_client(user.access_token), so Row Level Security scopes every pulse and
snapshot to the caller. On top of RLS, every read and write is also scoped to ONE care
recipient (child_id): the index is per-recipient (section 4.8), so the public reads
resolve which recipient through profile.resolve_child_id (an explicit child_id verified
owned, else the caller's sole child) and pass that one id down to every pulse/snapshot
query (.eq("child_id", ...)). This is the isolation rule (the board's law): no read
combines or averages two recipients' pulses or snapshots. A caller with no recipient yet
resolves to None and reads the empty (not-started) baseline. The six chapters are the
fixed Chapter set.

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
from app.models.chapters import Chapter
from app.models.lci import ChapterLci, OverallLci
from app.models.seed import Tier
from app.services.profile import _rows, resolve_child_id
from app.services.timestamps import parse_timestamptz

PULSE_RECORD_TABLE = "pulse_record"
LCI_SNAPSHOT_TABLE = "lci_snapshot"


# ---------------------------------------------------------------------------
# reads (the dashboard + the LCI endpoints)
# ---------------------------------------------------------------------------


def chapter_lci_list(
    user: AuthedUser, *, child_id: Optional[str] = None, now: Optional[datetime] = None
) -> List[ChapterLci]:
    """The per-chapter LCI for ONE care recipient: one ChapterLci per fixed Life Chapter.

    Resolves which recipient through profile.resolve_child_id (an explicit child_id
    verified owned, else the caller's sole child) and reads only THAT recipient's pulses
    (grouped by chapter) and snapshots, then for each of the six chapters computes the
    current score (engine fold), the pulse count, the trajectory vs the 7-days-prior
    snapshot, and the sparse label. A chapter with no pulse is score=null, pulse_count=0,
    label "--", trajectory building_picture; a caller with no recipient yet reads every
    chapter at that empty baseline. Always returns all six in the stable Chapter order.
    No chapter ever mixes two recipients' pulses (the isolation rule).
    """
    base_now = _utc_now(now)
    resolved_child_id = resolve_child_id(user, child_id)
    pulses_by_chapter = _pulses_by_chapter(user, resolved_child_id)
    snapshots_by_chapter = _snapshots_by_chapter(user, resolved_child_id)
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


def overall_lci(
    user: AuthedUser, *, child_id: Optional[str] = None, now: Optional[datetime] = None
) -> OverallLci:
    """The overall LCI for ONE care recipient: the equal-weighted mean of chapters with a pulse.

    Resolves the recipient (resolve_child_id), builds that recipient's per-chapter list,
    takes the mean of the chapters that have a score (no-data chapters excluded, never
    zero), and derives the overall trajectory by comparing the current overall to the
    overall reconstructed from the recipient's 7-days-prior snapshots (the same look-back
    instant for every chapter). chapters_included lists the chapters that contributed. The
    overall label uses the total pulse count across the included chapters (sparse while
    fewer than 3 pulses exist anywhere). The overall is a single recipient's resilience,
    never a household-aggregate score across recipients (the isolation rule).
    """
    base_now = _utc_now(now)
    resolved_child_id = resolve_child_id(user, child_id)
    chapters = chapter_lci_list(user, child_id=resolved_child_id, now=base_now)

    included = [c for c in chapters if c.score is not None]
    current = overall_score([c.score for c in chapters])

    prior = _overall_prior(user, resolved_child_id, base_now)
    total_pulses = sum(c.pulse_count for c in included)

    return OverallLci(
        score=current,
        trajectory=trajectory(current, prior),
        chapters_included=[Chapter(c.chapter) for c in included],
        label=label_for(total_pulses),
        timestamp=base_now,
    )


def _overall_prior(user: AuthedUser, child_id: Optional[str], now: datetime) -> Optional[int]:
    """The recipient's overall score 7 days prior, from each chapter's latest old-enough snapshot.

    For the overall trajectory: take each chapter's snapshot score at or before
    (now - 7 days) for THIS recipient and average the ones that exist, the same
    equal-weighted mean the current overall uses. None when no chapter has a 7-days-prior
    snapshot yet (the overall then reads building_picture).
    """
    look_back = prior_instant(now)
    snapshots_by_chapter = _snapshots_by_chapter(user, child_id)
    prior_scores = [
        snapshot_score_as_of(snaps, look_back) for snaps in snapshots_by_chapter.values()
    ]
    return overall_score(prior_scores)


# ---------------------------------------------------------------------------
# write (the post-pulse recompute, called from the Pulse service)
# ---------------------------------------------------------------------------


def recompute_chapter_lci(
    user: AuthedUser, chapter: str, child_id: str, *, now: Optional[datetime] = None
) -> int:
    """Recompute ONE recipient's chapter LCI from its pulses and record a fresh snapshot.

    Called after a Pulse is recorded (section 4.7 step 2, within 10 seconds): re-folds
    THIS recipient's full pulse history for the chapter into the current score
    (section 4.8) and inserts an lci_snapshot row (carrying child_id) capturing it, so
    the weekly trajectory and the "declining 3 snapshots" rule have the point. child_id
    comes from the activity_record the pulse was for (the pulse service passes it), so the
    recompute reads and writes exactly that recipient's history. Returns the new chapter
    score (always a value: the recompute runs only after a pulse exists for the chapter).
    The fold is over the stored outcomes and the stored recommended tiers, never a
    re-derived tier.
    """
    base_now = _utc_now(now)
    pulses = _pulses_by_chapter(user, child_id).get(chapter, [])
    score = chapter_score(pulses)
    if score is None:
        # Defensive: the recompute is only triggered after a pulse is written, so the
        # chapter always has at least one. If it somehow has none, there is nothing to
        # snapshot; start at the engine's starting value is not appropriate (no pulse),
        # so report the floor without writing a snapshot.
        return 0
    _insert_snapshot(user, chapter=chapter, child_id=child_id, score=score, taken_at=base_now)
    return score


def _insert_snapshot(
    user: AuthedUser, *, chapter: str, child_id: str, score: int, taken_at: datetime
) -> None:
    """Insert one lci_snapshot row (user + recipient scoped) capturing a chapter's score now.

    child_id is written on every snapshot so the per-recipient trajectory and alert
    history read only this recipient's points; it is the activity's child_id (the pulse
    service supplies it), never the client's.
    """
    client = get_anon_client(user.access_token)
    client.table(LCI_SNAPSHOT_TABLE).insert(
        {
            "user_id": user.id,
            "child_id": child_id,
            "chapter": chapter,
            "score": score,
            "taken_at": taken_at.isoformat(),
        }
    ).execute()


# ---------------------------------------------------------------------------
# fetch + map (stored rows -> the engine's pure inputs)
# ---------------------------------------------------------------------------


def _pulses_by_chapter(user: AuthedUser, child_id: Optional[str]) -> Dict[str, List[PulsePoint]]:
    """ONE recipient's pulses as engine PulsePoints, grouped by chapter code.

    Reads the pulse_record rows for THIS recipient under RLS (filtered by user_id AND
    child_id: outcome, tier, chapter, created_at) and maps each to the minimal triple the
    index folds. child_id None means the caller has no recipient yet, so there is nothing
    to read and the fold is empty (the not-started baseline); the query is skipped. A row
    with an unparseable outcome or tier is skipped (the column CHECKs make that unreachable
    in practice; the guard keeps a bad row from breaking the whole dashboard).
    """
    if child_id is None:
        return defaultdict(list)
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE)
        .select("chapter, outcome_code, tier_recommended, created_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
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


def _snapshots_by_chapter(user: AuthedUser, child_id: Optional[str]) -> Dict[str, List[Snapshot]]:
    """ONE recipient's LCI snapshots as engine Snapshots, grouped by chapter code.

    Filters lci_snapshot by user_id AND child_id (migration 0009), so the trajectory
    only ever sees this recipient's history. child_id None (no recipient yet) reads
    nothing (the query is skipped).
    """
    if child_id is None:
        return defaultdict(list)
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(LCI_SNAPSHOT_TABLE)
        .select("chapter, score, taken_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
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


def chapter_scores_by_code(
    user: AuthedUser, child_id: Optional[str] = None
) -> Dict[str, Optional[int]]:
    """ONE recipient's current LCI per chapter code (the dashboard wiring, ChapterStatus.lci).

    A thin helper the chapters dashboard service and the alerts service call: maps each
    chapter code to this recipient's current score (None for a chapter with no pulse).
    The caller passes an already-resolved child_id (the dashboard resolves it once and
    threads it here and to the alerts service, so the card, the LCI dashboard, and the
    alert all read the SAME recipient and agree). Only chapters with a pulse get a value;
    the rest are absent (the caller defaults them to null). Reuses the same per-recipient
    pulse fold as the LCI endpoints.
    """
    pulses_by_chapter = _pulses_by_chapter(user, child_id)
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
    return parse_timestamptz(value)
