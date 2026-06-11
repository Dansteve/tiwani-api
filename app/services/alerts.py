"""Erosion Alert data + evaluation service (v3).

The layer between the pure alert engine (app/engines/alerts) and Supabase. It is the
post-pulse hook: after a Pulse is recorded and the chapter LCI is recomputed
(app/services/pulse.py), it fetches the chapter's activity_record / pulse_record /
lci_snapshot history (RLS-scoped), builds the engine's ChapterHistory, calls
evaluate() (section 4.9, AUTHORITATIVE), and UPSERTs the per-chapter alert_record. It
also serves GET /api/v3/alerts (the active, non-dismissed alerts with their governed
copy) and the dismiss endpoint, and supplies the dashboard's per-chapter alert_level.

No threshold logic lives here: the engine owns section 4.9. This service only fetches
the rows, supplies `now`, persists the result, and applies the DISMISSAL rule (a
dismissed alert returns only if conditions worsen past the next threshold).

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every read and write
runs through get_anon_client(user.access_token), so Row Level Security scopes every
row to the caller. The post-pulse evaluation is NON-INTERRUPTING: it is wrapped so a
failure to evaluate or persist an alert never fails the pulse the Coordinator just
recorded (the alert is a background signal, section 4.9 / KB 1.6).

GOVERNED COPY + LAUNCH GATE: the copy this service surfaces (via app/engines/alerts/
copy.py) is governed and does not ship to beta without psychiatrist sign-off (Task 12).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.engines.alerts import (
    ActivityPoint,
    AlertLevel,
    ChapterHistory,
    PulseOutcomePoint,
    evaluate,
    render_alert,
)
from app.engines.lci import Outcome
from app.models.alert import AlertView, DismissResult, SignpostView
from app.models.chapters_v3 import Chapter
from app.models.seed import Tier
from app.services import lci as lci_service
from app.services.profile import _first, _rows

ACTIVITY_RECORD_TABLE = "activity_record"
PULSE_RECORD_TABLE = "pulse_record"
LCI_SNAPSHOT_TABLE = "lci_snapshot"
ALERT_RECORD_TABLE = "alert_record"

logger = logging.getLogger(__name__)

# The stable trigger-condition codes written to alert_record.trigger_condition (the
# section 4.9 branch that fired the active level). Audit/QA only; the level is the
# structured signal.
TRIGGER_L1_COUNTS = "l1_counts_30d"
TRIGGER_L2_COUNTS = "l2_counts_30d"
TRIGGER_L2_LCI_DECLINE = "l2_lci_decline_3wk"
TRIGGER_L3_COUNTS = "l3_counts_14d"
TRIGGER_L3_LCI = "l3_lci_below_30"


class AlertNotFoundError(Exception):
    """Raised when dismissing a chapter that has no active alert (route maps to 404)."""


# ---------------------------------------------------------------------------
# the post-pulse hook (called from app/services/pulse.py)
# ---------------------------------------------------------------------------


def evaluate_chapter_alert(
    user: AuthedUser, chapter: str, *, now: Optional[datetime] = None
) -> Optional[AlertLevel]:
    """Evaluate and persist the Erosion Alert for one chapter after a Pulse (section 4.9).

    The post-pulse hook (app/services/pulse.py step 3): builds the chapter's
    ChapterHistory from the stored rows, runs the pure engine, and reconciles the
    alert_record:
      - computed None  -> clear any active alert (delete the row).
      - computed level -> UPSERT, honouring dismissal: a dismissed alert returns only
        if `computed` is strictly higher than the level it was dismissed at; otherwise
        it stays dismissed (its latent level is still updated) and does not resurface.
    Returns the computed level (or None). `now` is injectable for tests; defaults to
    UTC now and is the only clock the evaluation uses.
    """
    base_now = _utc_now(now)
    history = _build_history(user, chapter, now=base_now)
    computed = evaluate(history, now=base_now)
    _reconcile_alert_record(user, chapter, computed, history)
    return computed


def evaluate_chapter_alert_safe(
    user: AuthedUser, chapter: str, *, now: Optional[datetime] = None
) -> None:
    """evaluate_chapter_alert wrapped so it NEVER raises into the pulse flow.

    The alert is a background signal (section 4.9 / KB 1.6: it does not interrupt the
    user experience). The pulse and the LCI recompute have already succeeded by the
    time this runs; if the alert evaluation or its write fails, we log and swallow so
    the Coordinator's recorded pulse is not lost to an alerting problem.
    """
    try:
        evaluate_chapter_alert(user, chapter, now=now)
    except Exception:  # noqa: BLE001 - the alert must never fail the pulse
        logger.exception("Erosion Alert evaluation failed for chapter %s", chapter)


# ---------------------------------------------------------------------------
# reads (GET /api/v3/alerts + the dashboard wiring)
# ---------------------------------------------------------------------------


def list_active_alerts(user: AuthedUser) -> List[AlertView]:
    """The user's active (non-dismissed) Erosion Alerts, each with its governed copy.

    Reads the alert_record rows (RLS-scoped), keeps the non-dismissed ones, and
    renders each through the GOVERNED copy module (the verbatim section 4.9 prompt +
    action label + the chapter's community/statutory signposts), guarded. Returned in
    the stable Chapter order so the dashboard is deterministic.
    """
    rows = _active_rows(user)
    by_chapter = {r.get("chapter"): r for r in rows}

    views: List[AlertView] = []
    for chapter in Chapter:
        row = by_chapter.get(chapter.value)
        if row is None:
            continue
        level = _level_from_row(row)
        if level is None:
            continue
        views.append(_to_alert_view(chapter, level))
    return views


def active_levels_by_chapter(user: AuthedUser) -> Dict[str, int]:
    """The active (non-dismissed) alert level per chapter code, for the dashboard.

    A thin helper the chapters dashboard service calls to fill
    ChapterStatus.alert_level: maps each chapter code that has an ACTIVE alert to its
    level (1/2/3). Chapters with no active alert are absent (the caller defaults them
    to null). Reads the same alert_record rows the alerts endpoint does, so the
    dashboard and the alerts list agree.
    """
    levels: Dict[str, int] = {}
    for row in _active_rows(user):
        chapter = row.get("chapter")
        level = _level_from_row(row)
        if chapter is not None and level is not None:
            levels[chapter] = int(level)
    return levels


# ---------------------------------------------------------------------------
# dismissal (POST /api/v3/alerts/{chapter}/dismiss)
# ---------------------------------------------------------------------------


def dismiss_alert(user: AuthedUser, chapter: str) -> DismissResult:
    """Dismiss the chapter's active alert (section 4.9): it returns only on worsening.

    Marks the active alert_record dismissed and records the level it was dismissed at
    (dismissed_level), so the next post-pulse evaluation resurfaces it only if it
    computes a strictly higher level. Raises AlertNotFoundError (404) if the chapter
    has no active alert to dismiss.
    """
    row = _alert_row(user, chapter)
    if row is None or row.get("dismissed"):
        raise AlertNotFoundError("No active alert for this chapter")
    level = _level_from_row(row)
    if level is None:
        raise AlertNotFoundError("No active alert for this chapter")

    client = get_anon_client(user.access_token)
    client.table(ALERT_RECORD_TABLE).update(
        {"dismissed": True, "dismissed_level": int(level)}
    ).eq("user_id", user.id).eq("chapter", chapter).execute()

    return DismissResult(chapter=Chapter(chapter), dismissed_level=int(level))


# ---------------------------------------------------------------------------
# building the engine inputs from the stored rows
# ---------------------------------------------------------------------------


def _build_history(user: AuthedUser, chapter: str, *, now: datetime) -> ChapterHistory:
    """Assemble the chapter's ChapterHistory (activities, pulses, LCI, weekly snapshots).

    Reads the chapter's activity_record (tier + created_at), pulse_record (outcome +
    created_at), and lci_snapshot history (RLS-scoped), plus the chapter's CURRENT
    section 4.8 score (the shared lci_service fold, so the alert and the dashboard
    agree). Rows whose codes do not parse are skipped (the column CHECKs make that
    unreachable in practice). The weekly snapshot scores are reduced to one point per
    ISO week, oldest-first, for the "declining 3 weekly snapshots" condition.
    """
    activities = _chapter_activities(user, chapter)
    pulses = _chapter_pulses(user, chapter)
    current_lci = lci_service.chapter_scores_by_code(user).get(chapter)
    weekly_scores = _weekly_snapshot_scores(user, chapter)
    return ChapterHistory(
        activities=activities,
        pulses=pulses,
        current_lci=current_lci,
        weekly_snapshot_scores=weekly_scores,
    )


def _chapter_activities(user: AuthedUser, chapter: str) -> List[ActivityPoint]:
    """The chapter's prepared activities as engine ActivityPoints (tier + created_at)."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("tier, created_at")
        .eq("user_id", user.id)
        .eq("chapter", chapter)
        .execute()
    )
    points: List[ActivityPoint] = []
    for row in rows:
        try:
            tier = Tier(row.get("tier"))
        except ValueError:
            continue
        at = _parse_dt(row.get("created_at"))
        if at is None:
            continue
        points.append(ActivityPoint(tier=tier, at=at))
    return points


def _chapter_pulses(user: AuthedUser, chapter: str) -> List[PulseOutcomePoint]:
    """The chapter's recorded pulses as engine PulseOutcomePoints (outcome + created_at)."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE)
        .select("outcome_code, created_at")
        .eq("user_id", user.id)
        .eq("chapter", chapter)
        .execute()
    )
    points: List[PulseOutcomePoint] = []
    for row in rows:
        try:
            outcome = Outcome(row.get("outcome_code"))
        except ValueError:
            continue
        at = _parse_dt(row.get("created_at"))
        if at is None:
            continue
        points.append(PulseOutcomePoint(outcome=outcome, at=at))
    return points


def _weekly_snapshot_scores(user: AuthedUser, chapter: str) -> List[int]:
    """The chapter's LCI snapshots reduced to one score per ISO week, oldest-first.

    The section 4.9 L2 condition is "the chapter LCI declining for 3 weekly snapshots
    in a row". Snapshots are written on every pulse (potentially several in a week), so
    we collapse them to ONE value per ISO (year, week): the LATEST snapshot in that
    week (its end-of-week score). The resulting series is ordered oldest week first, so
    the engine can test the most recent run of weekly drops. Weeks with no snapshot are
    simply absent (a gap is not a decline).
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(LCI_SNAPSHOT_TABLE)
        .select("score, taken_at")
        .eq("user_id", user.id)
        .eq("chapter", chapter)
        .execute()
    )

    # latest snapshot per ISO week: key (iso_year, iso_week) -> (taken_at, score)
    latest_per_week: Dict[tuple, tuple] = {}
    for row in rows:
        taken_at = _parse_dt(row.get("taken_at"))
        score = row.get("score")
        if taken_at is None or score is None:
            continue
        iso = taken_at.isocalendar()
        key = (iso[0], iso[1])
        existing = latest_per_week.get(key)
        if existing is None or taken_at > existing[0]:
            latest_per_week[key] = (taken_at, int(score))

    ordered_keys = sorted(latest_per_week.keys())
    return [latest_per_week[k][1] for k in ordered_keys]


# ---------------------------------------------------------------------------
# persisting the result (the upsert + the dismissal rule)
# ---------------------------------------------------------------------------


def _reconcile_alert_record(
    user: AuthedUser,
    chapter: str,
    computed: Optional[AlertLevel],
    history: ChapterHistory,
) -> None:
    """Write the alert_record to match the computed level, honouring dismissal.

    - computed None: delete any existing alert for the chapter (nothing to show).
    - existing dismissed at D: the alert returns only if computed > D (re-activate);
      otherwise keep it dismissed (update its latent level/trigger, stay hidden).
    - existing active: update its level + trigger to the computed value.
    - no row: insert a fresh active alert at the computed level.
    """
    client = get_anon_client(user.access_token)
    existing = _alert_row(user, chapter)

    if computed is None:
        if existing is not None:
            client.table(ALERT_RECORD_TABLE).delete().eq("user_id", user.id).eq(
                "chapter", chapter
            ).execute()
        return

    trigger = _trigger_condition(computed, history)

    if existing is None:
        client.table(ALERT_RECORD_TABLE).insert(
            {
                "user_id": user.id,
                "chapter": chapter,
                "level": int(computed),
                "trigger_condition": trigger,
                "dismissed": False,
                "dismissed_level": None,
            }
        ).execute()
        return

    if existing.get("dismissed"):
        dismissed_level = existing.get("dismissed_level") or 0
        if int(computed) > int(dismissed_level):
            # Worsened past the next threshold: the alert returns at the higher level.
            client.table(ALERT_RECORD_TABLE).update(
                {
                    "level": int(computed),
                    "trigger_condition": trigger,
                    "dismissed": False,
                    "dismissed_level": None,
                }
            ).eq("user_id", user.id).eq("chapter", chapter).execute()
        else:
            # Not worse than what was dismissed: keep it hidden, track the latent level.
            client.table(ALERT_RECORD_TABLE).update(
                {"level": int(computed), "trigger_condition": trigger}
            ).eq("user_id", user.id).eq("chapter", chapter).execute()
        return

    # An active (non-dismissed) alert: update to the computed level (higher replaces
    # lower, and a drop to a still-active level updates it too).
    client.table(ALERT_RECORD_TABLE).update(
        {"level": int(computed), "trigger_condition": trigger}
    ).eq("user_id", user.id).eq("chapter", chapter).execute()


def _trigger_condition(level: AlertLevel, history: ChapterHistory) -> str:
    """The stable code naming which section 4.9 branch fired the level (audit only).

    For L2 and L3 (which have two OR branches) it distinguishes the counts branch from
    the LCI branch by re-checking the LCI conditions on the history; the engine already
    decided the level, this only labels WHY for the stored row.
    """
    if level is AlertLevel.L3:
        if history.current_lci is not None and history.current_lci < 30:
            return TRIGGER_L3_LCI
        return TRIGGER_L3_COUNTS
    if level is AlertLevel.L2:
        # If the counts branch is not met, the LCI decline branch must have fired.
        from app.engines.alerts.evaluation import _lci_declining

        if _lci_declining(history.weekly_snapshot_scores):
            return TRIGGER_L2_LCI_DECLINE
        return TRIGGER_L2_COUNTS
    return TRIGGER_L1_COUNTS


# ---------------------------------------------------------------------------
# row access + shaping
# ---------------------------------------------------------------------------


def _alert_row(user: AuthedUser, chapter: str) -> Optional[Dict[str, Any]]:
    """The user's alert_record row for a chapter (active or dismissed), or None."""
    client = get_anon_client(user.access_token)
    return _first(
        client.table(ALERT_RECORD_TABLE)
        .select("chapter, level, trigger_condition, dismissed, dismissed_level")
        .eq("user_id", user.id)
        .eq("chapter", chapter)
        .execute()
    )


def _active_rows(user: AuthedUser) -> List[Dict[str, Any]]:
    """All the user's alert_record rows that are NOT dismissed (the active alerts)."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ALERT_RECORD_TABLE)
        .select("chapter, level, trigger_condition, dismissed, dismissed_level")
        .eq("user_id", user.id)
        .eq("dismissed", False)
        .execute()
    )
    return [r for r in rows if not r.get("dismissed")]


def _level_from_row(row: Dict[str, Any]) -> Optional[AlertLevel]:
    """The AlertLevel from a stored row's `level`, or None if it does not parse."""
    raw = row.get("level")
    if raw is None:
        return None
    try:
        return AlertLevel(int(raw))
    except (ValueError, TypeError):
        return None


def _to_alert_view(chapter: Chapter, level: AlertLevel) -> AlertView:
    """Render a chapter+level into the AlertView the app gets (governed copy, guarded)."""
    rendered = render_alert(chapter, level)
    return AlertView(
        chapter=chapter,
        level=int(level),
        copy_text=rendered.prompt,
        action_label=rendered.action_label,
        signposts=[SignpostView(label=s.label, url=s.url) for s in rendered.signposts],
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _utc_now(now: Optional[datetime]) -> datetime:
    if now is not None:
        return now
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a timestamptz value (ISO string or datetime) to an aware datetime."""
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
