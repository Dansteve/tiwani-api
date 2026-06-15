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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.lci import (
    Outcome,
    PulsePoint,
    Snapshot,
    band_for,
    chapter_score,
    label_for,
    overall_score,
    prior_instant,
    snapshot_score_as_of,
    trajectory,
)
from app.models.chapters import Chapter
from app.models.lci import (
    ChapterLci,
    LciHistory,
    LciHistoryPoint,
    LciSeries,
    OverallLci,
)
from app.models.seed import Tier
from app.services.pagination import MAX_BOUNDED_ROWS
from app.services.profile import _rows, resolve_child_id
from app.services.timestamps import parse_timestamptz

PULSE_RECORD_TABLE = "pulse_record"
LCI_SNAPSHOT_TABLE = "lci_snapshot"

# The check-in history staleness window (section 4.3 / Decisions.md D15 honesty-in-time):
# lci_snapshot rows are written event-driven (one per pulse), so a chapter with no new
# reading for this many days is "stale", and the history view STOPS rather than carry the
# last score forward as a live in-band line. The api owns this flag; the app renders it.
HISTORY_STALE_AFTER_DAYS = 14


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
# read (the check-in history view: GET /api/v1/lci/history)
# ---------------------------------------------------------------------------


def lci_history(
    user: AuthedUser, *, child_id: Optional[str] = None, now: Optional[datetime] = None
) -> LciHistory:
    """ONE care recipient's DISCRETE LCI history: the overall + per-chapter recorded points.

    The read behind the "Your check-in history" view (the de-risked timeline). Resolves
    the recipient (resolve_child_id), reads only THAT recipient's stored lci_snapshot rows
    (RLS + child_id scoped), and turns them into discrete points: each chapter series is
    its snapshots in time order (score + the section 4.3 band), and the overall series is
    the equal-weighted overall reconstructed at each distinct snapshot instant (the same
    mean the live overall uses, never a re-scored value). Every series carries the honesty
    signals the app cannot lie without: reading_count (the three-reading floor),
    latest_taken_at (after which the series stops), and is_stale (older than the staleness
    window). This is a READ of stored snapshots: no new engine, no new score, no decline
    language. Always returns all six chapter series in the stable Chapter order.
    """
    base_now = _utc_now(now)
    resolved_child_id = resolve_child_id(user, child_id)
    snapshots_by_chapter = _snapshots_by_chapter(user, resolved_child_id)

    chapter_series = [
        _series_from_snapshots(
            chapter.value, snapshots_by_chapter.get(chapter.value, []), base_now
        )
        for chapter in Chapter
    ]
    overall_series = _overall_series(snapshots_by_chapter, base_now)

    return LciHistory(
        overall=overall_series,
        chapters=chapter_series,
        generated_at=base_now,
    )


def _series_from_snapshots(scope: str, snapshots: List[Snapshot], now: datetime) -> LciSeries:
    """One scope's LciSeries from its stored snapshots: discrete points + the honesty signals.

    The snapshots are sorted ascending by instant and each becomes a discrete point
    carrying its real timestamp, its score, and the section 4.3 band (band_for). The
    honesty signals are derived here so the api owns them: reading_count is how many real
    readings there are (the three-reading floor), latest_taken_at is the last reading's
    instant (the series stops there), and is_stale is true when that last reading is older
    than the staleness window (the view then degrades to "no reading since [date]" rather
    than carrying the score forward).
    """
    ordered = sorted(snapshots, key=lambda s: s.taken_at)
    points = [
        LciHistoryPoint(taken_at=s.taken_at, score=s.score, band=band_for(s.score))
        for s in ordered
    ]
    latest = ordered[-1].taken_at if ordered else None
    return LciSeries(
        scope=scope,
        points=points,
        reading_count=len(points),
        latest_taken_at=latest,
        is_stale=_is_stale(latest, now),
    )


def _overall_series(snapshots_by_chapter: Dict[str, List[Snapshot]], now: datetime) -> LciSeries:
    """The OVERALL discrete history: the equal-weighted overall at each distinct snapshot instant.

    Walks the union of every chapter's snapshot instants in time order; at each instant it
    takes each chapter's latest-known score at or before that instant and averages the ones
    that exist (overall_score, the same equal-weighted mean the live overall uses), giving
    the overall value then. Consecutive duplicate values are collapsed so a point is emitted
    only where the overall actually CHANGED (a real reading moment), keeping the series the
    honest set of distinct overall readings rather than a dense restatement. No re-scoring:
    every input score is a stored snapshot value. The honesty signals mirror a chapter
    series (reading_count, latest_taken_at, is_stale).
    """
    instants = sorted({s.taken_at for snaps in snapshots_by_chapter.values() for s in snaps})

    points: List[LciHistoryPoint] = []
    last_score: Optional[int] = None
    for instant in instants:
        scores = [
            snapshot_score_as_of(snaps, instant) for snaps in snapshots_by_chapter.values()
        ]
        value = overall_score(scores)
        if value is None or value == last_score:
            continue
        points.append(
            LciHistoryPoint(taken_at=instant, score=value, band=band_for(value))
        )
        last_score = value

    latest = points[-1].taken_at if points else None
    return LciSeries(
        scope="overall",
        points=points,
        reading_count=len(points),
        latest_taken_at=latest,
        is_stale=_is_stale(latest, now),
    )


def _is_stale(latest_taken_at: Optional[datetime], now: datetime) -> bool:
    """True when the last reading is older than the staleness window (stale = stop, do not lie).

    No reading at all is not "stale" (it is the empty/building state, handled by
    reading_count); a series is stale only when it HAS a last reading and that reading is
    older than HISTORY_STALE_AFTER_DAYS, so the view shows "no reading since [date]" instead
    of a live in-band line.
    """
    if latest_taken_at is None:
        return False
    return now - latest_taken_at > timedelta(days=HISTORY_STALE_AFTER_DAYS)


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

    DELIBERATELY NOT ROW-CAPPED (the every-list-is-capped rule's one exception): the chapter
    LCI (section 4.8, AUTHORITATIVE) folds the COMPLETE pulse history per chapter, so a flat
    row `.limit(...)` that dropped older pulses would CHANGE the score and break the spec.
    Completeness of this scoring input wins over a safety cap (the cap exists to protect the
    query, never to corrupt the authoritative number); the bound here is the RLS + per-chapter
    grouping, not a row limit. The list endpoints this feeds (/lci/chapters, /lci/overall)
    still return a bounded response (the six fixed chapters), and the snapshot read above
    (the trajectory + history input, not a scoring input) IS capped.
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

    BOUNDED (the every-list-is-capped rule): the snapshot read powers the trajectory
    look-back (the snapshot at/before now - 7 days) and the check-in history view (a recent,
    14-day-staleness-windowed timeline), so it only ever needs RECENT snapshots, never the
    whole history. The read is ordered MOST-RECENT-first and carries a hard MAX_BOUNDED_ROWS
    `.limit(...)` so a long-running recipient's accumulating snapshots can never make it
    unbounded. Capping the MOST RECENT is safe here (unlike the pulse fold below): snapshots
    drive only the trajectory comparison and the history DISPLAY, never the AUTHORITATIVE
    section 4.8 score (that folds the pulses), and the recent window the cap keeps far
    exceeds the 7-day look-back and the 14-day history window. No cursor: the response is the
    six fixed chapters (the LCI reads) or a recent series (the history view).
    """
    if child_id is None:
        return defaultdict(list)
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(LCI_SNAPSHOT_TABLE)
        .select("chapter, score, taken_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .order("taken_at", desc=True)
        .limit(MAX_BOUNDED_ROWS)
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
