"""Erosion Alert data + evaluation service (v3).

The layer between the pure alert engine (app/engines/alerts) and Supabase. It is the
post-pulse hook: after a Pulse is recorded and the chapter LCI is recomputed
(app/services/pulse.py), it fetches the chapter's activity_record / pulse_record /
lci_snapshot history (RLS-scoped), builds the engine's ChapterHistory, calls
evaluate() (section 4.9, AUTHORITATIVE), and UPSERTs the per-chapter alert_record. It
also serves GET /api/v1/alerts (the active, non-dismissed alerts with their governed
copy) and the dismiss endpoint, and supplies the dashboard's per-chapter alert_level.

No threshold logic lives here: the engine owns section 4.9. This service only fetches
the rows, supplies `now`, persists the result, and applies the DISMISSAL rule (a
dismissed alert returns only if conditions worsen past the next threshold).

User + recipient scoping and RLS (Auth.md, Models.md; Docs/FeatureDecisions.md, the
multi care recipient design note): every read and write runs through
get_anon_client(user.access_token), so Row Level Security scopes every row to the caller.
On top of RLS, every alert is PER RECIPIENT (child_id): the post-pulse evaluation reads
and writes the alert_record / activity / pulse / snapshot rows for the activity's OWN
recipient (the pulse service passes its child_id), and the read paths (the alerts list,
the dashboard levels, the dismiss) scope to the resolved recipient. The active-alert
unique key is (user_id, child_id, chapter) (migration 0010), so two recipients keep
SEPARATE alert rows per chapter: one recipient's evaluation never overwrites another's,
and a dismissal for one never silences the other. No alert read combines two recipients
(the isolation rule); alerts stay per-recipient and calm. The post-pulse evaluation is
NON-INTERRUPTING: it is wrapped so a failure to evaluate or persist an alert never fails
the pulse the Coordinator just recorded (the alert is a background signal, section 4.9 /
KB 1.6).

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
from app.models.chapters import Chapter
from app.models.seed import Tier
from app.services import lci as lci_service
from app.services.pagination import MAX_BOUNDED_ROWS
from app.services.profile import _first, _rows, resolve_child_id
from app.services.timestamps import parse_timestamptz

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
    user: AuthedUser, chapter: str, child_id: str, *, now: Optional[datetime] = None
) -> Optional[AlertLevel]:
    """Evaluate and persist ONE recipient's Erosion Alert for a chapter after a Pulse (section 4.9).

    The post-pulse hook (app/services/pulse.py step 4): builds the chapter's ChapterHistory
    from the stored rows FOR THIS recipient (the activity's own child_id, passed in), runs
    the pure engine, and reconciles that recipient's alert_record (keyed by
    (user_id, child_id, chapter), migration 0010):
      - computed None  -> clear any active alert for this recipient+chapter (delete the row).
      - computed level -> UPSERT, honouring dismissal: a dismissed alert returns only
        if `computed` is strictly higher than the level it was dismissed at; otherwise
        it stays dismissed (its latent level is still updated) and does not resurface.
    A different recipient's alert for the same chapter is a separate row and is untouched.
    Returns the computed level (or None). `now` is injectable for tests; defaults to
    UTC now and is the only clock the evaluation uses.
    """
    base_now = _utc_now(now)
    history = _build_history(user, chapter, child_id, now=base_now)
    computed = evaluate(history, now=base_now)
    _reconcile_alert_record(user, chapter, child_id, computed, history)
    return computed


def evaluate_chapter_alert_safe(
    user: AuthedUser, chapter: str, child_id: str, *, now: Optional[datetime] = None
) -> None:
    """evaluate_chapter_alert wrapped so it NEVER raises into the pulse flow.

    The alert is a background signal (section 4.9 / KB 1.6: it does not interrupt the
    user experience). The pulse and the LCI recompute have already succeeded by the
    time this runs; if the alert evaluation or its write fails, we log and swallow so
    the Coordinator's recorded pulse is not lost to an alerting problem. child_id is the
    activity's own recipient, so the evaluation stays scoped to that one recipient.
    """
    try:
        evaluate_chapter_alert(user, chapter, child_id, now=now)
    except Exception:  # noqa: BLE001 - the alert must never fail the pulse
        logger.exception("Erosion Alert evaluation failed for chapter %s", chapter)


# ---------------------------------------------------------------------------
# reads (GET /api/v1/alerts + the dashboard wiring)
# ---------------------------------------------------------------------------


def list_active_alerts(user: AuthedUser, child_id: Optional[str] = None) -> List[AlertView]:
    """ONE recipient's active (non-dismissed) Erosion Alerts, each with its governed copy.

    Resolves which recipient (resolve_child_id, an explicit child_id verified owned, else
    the caller's sole child) and reads only THAT recipient's alert_record rows (RLS +
    child_id scoped), keeps the non-dismissed ones, and renders each through the GOVERNED
    copy module (the verbatim section 4.9 prompt + action label + the chapter's
    community/statutory signposts), guarded. Returned in the stable Chapter order so the
    dashboard is deterministic. A caller with no recipient yet has no alerts. The list is
    one recipient's alerts, never two recipients pooled (the isolation rule).
    """
    resolved_child_id = resolve_child_id(user, child_id)
    rows = _active_rows(user, resolved_child_id)
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


def active_levels_by_chapter(user: AuthedUser, child_id: Optional[str] = None) -> Dict[str, int]:
    """ONE recipient's active (non-dismissed) alert level per chapter code, for the dashboard.

    A thin helper the chapters dashboard service calls to fill ChapterStatus.alert_level:
    maps each chapter code that has an ACTIVE alert FOR THIS recipient to its level (1/2/3).
    The caller passes an already-resolved child_id (the dashboard resolves it once and
    threads it here, the LCI scores, and the activity counts, so all three read the same
    recipient). Chapters with no active alert are absent (the caller defaults them to null).
    Reads the same per-recipient alert_record rows the alerts endpoint does, so the
    dashboard and the alerts list agree. child_id None (no recipient) yields no levels.
    """
    levels: Dict[str, int] = {}
    for row in _active_rows(user, child_id):
        chapter = row.get("chapter")
        level = _level_from_row(row)
        if chapter is not None and level is not None:
            levels[chapter] = int(level)
    return levels


# ---------------------------------------------------------------------------
# dismissal (POST /api/v1/alerts/{chapter}/dismiss)
# ---------------------------------------------------------------------------


def dismiss_alert(user: AuthedUser, chapter: str, child_id: Optional[str] = None) -> DismissResult:
    """Dismiss ONE recipient's chapter alert (section 4.9): it returns only on worsening.

    Resolves which recipient (resolve_child_id), then marks THAT recipient's active
    alert_record dismissed and records the level it was dismissed at (dismissed_level), so
    the next post-pulse evaluation resurfaces it only if it computes a strictly higher
    level. The update scopes by (user_id, child_id, chapter), so dismissing one recipient's
    alert never touches another recipient's alert for the same chapter. Raises
    AlertNotFoundError (404) if this recipient has no active alert for the chapter.
    """
    resolved_child_id = resolve_child_id(user, child_id)
    row = _alert_row(user, chapter, resolved_child_id)
    if row is None or row.get("dismissed"):
        raise AlertNotFoundError("No active alert for this chapter")
    level = _level_from_row(row)
    if level is None:
        raise AlertNotFoundError("No active alert for this chapter")

    client = get_anon_client(user.access_token)
    client.table(ALERT_RECORD_TABLE).update(
        {"dismissed": True, "dismissed_level": int(level)}
    ).eq("user_id", user.id).eq("child_id", resolved_child_id).eq("chapter", chapter).execute()

    return DismissResult(chapter=Chapter(chapter), dismissed_level=int(level))


# ---------------------------------------------------------------------------
# building the engine inputs from the stored rows
# ---------------------------------------------------------------------------


def _build_history(
    user: AuthedUser, chapter: str, child_id: str, *, now: datetime
) -> ChapterHistory:
    """Assemble ONE recipient's chapter ChapterHistory (activities, pulses, LCI, weekly snapshots).

    Reads THIS recipient's chapter activity_record (tier + created_at), pulse_record
    (outcome + created_at), and lci_snapshot history (RLS + child_id scoped), plus the
    recipient's CURRENT section 4.8 score (the shared lci_service fold for this child_id,
    so the alert, the card, and the dashboard agree). Every read is filtered by child_id,
    so the history is one recipient's and the engine never sees another recipient's
    activity or pulse. Rows whose codes do not parse are skipped (the column CHECKs make
    that unreachable in practice). The weekly snapshot scores are reduced to one point per
    ISO week, oldest-first, for the "declining 3 weekly snapshots" condition.
    """
    activities = _chapter_activities(user, chapter, child_id)
    pulses = _chapter_pulses(user, chapter, child_id)
    current_lci = lci_service.chapter_scores_by_code(user, child_id).get(chapter)
    weekly_scores = _weekly_snapshot_scores(user, chapter, child_id)
    return ChapterHistory(
        activities=activities,
        pulses=pulses,
        current_lci=current_lci,
        weekly_snapshot_scores=weekly_scores,
    )


def _chapter_activities(user: AuthedUser, chapter: str, child_id: str) -> List[ActivityPoint]:
    """THIS recipient's chapter activities as engine ActivityPoints (tier + created_at)."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("tier, created_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
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


def _chapter_pulses(user: AuthedUser, chapter: str, child_id: str) -> List[PulseOutcomePoint]:
    """THIS recipient's chapter pulses as engine PulseOutcomePoints (outcome + created_at)."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE)
        .select("outcome_code, created_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
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


def _weekly_snapshot_scores(user: AuthedUser, chapter: str, child_id: str) -> List[int]:
    """THIS recipient's chapter LCI snapshots reduced to one score per ISO week, oldest-first.

    The section 4.9 L2 condition is "the chapter LCI declining for 3 weekly snapshots
    in a row". Snapshots are written on every pulse (potentially several in a week), so
    we collapse them to ONE value per ISO (year, week): the LATEST snapshot in that
    week (its end-of-week score). The resulting series is ordered oldest week first, so
    the engine can test the most recent run of weekly drops. Weeks with no snapshot are
    simply absent (a gap is not a decline). The read is filtered by child_id, so the
    series is one recipient's.
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(LCI_SNAPSHOT_TABLE)
        .select("score, taken_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
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
    child_id: str,
    computed: Optional[AlertLevel],
    history: ChapterHistory,
) -> None:
    """Write THIS recipient's alert_record to match the computed level, honouring dismissal.

    Every read and write is scoped to (user_id, child_id, chapter), the new active-alert
    key (migration 0010), so this only ever touches the one recipient's alert for the
    chapter; a different recipient's alert for the same chapter is a separate row and is
    left alone.
    - computed None: delete this recipient's existing alert for the chapter (nothing to show).
    - existing dismissed at D: the alert returns only if computed > D (re-activate);
      otherwise keep it dismissed (update its latent level/trigger, stay hidden).
    - existing active: update its level + trigger to the computed value.
    - no row: insert a fresh active alert (carrying child_id) at the computed level.
    """
    client = get_anon_client(user.access_token)
    existing = _alert_row(user, chapter, child_id)

    if computed is None:
        if existing is not None:
            client.table(ALERT_RECORD_TABLE).delete().eq("user_id", user.id).eq(
                "child_id", child_id
            ).eq("chapter", chapter).execute()
        return

    trigger = _trigger_condition(computed, history)

    if existing is None:
        client.table(ALERT_RECORD_TABLE).insert(
            {
                "user_id": user.id,
                "child_id": child_id,
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
            ).eq("user_id", user.id).eq("child_id", child_id).eq("chapter", chapter).execute()
        else:
            # Not worse than what was dismissed: keep it hidden, track the latent level.
            client.table(ALERT_RECORD_TABLE).update(
                {"level": int(computed), "trigger_condition": trigger}
            ).eq("user_id", user.id).eq("child_id", child_id).eq("chapter", chapter).execute()
        return

    # An active (non-dismissed) alert: update to the computed level (higher replaces
    # lower, and a drop to a still-active level updates it too).
    client.table(ALERT_RECORD_TABLE).update(
        {"level": int(computed), "trigger_condition": trigger}
    ).eq("user_id", user.id).eq("child_id", child_id).eq("chapter", chapter).execute()


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


def _alert_row(user: AuthedUser, chapter: str, child_id: str) -> Optional[Dict[str, Any]]:
    """THIS recipient's alert_record row for a chapter (active or dismissed), or None.

    Scoped to (user_id, child_id, chapter), the new active-alert key (migration 0010), so
    it reads exactly the one recipient's alert for the chapter.
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(ALERT_RECORD_TABLE)
        .select("chapter, level, trigger_condition, dismissed, dismissed_level")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("chapter", chapter)
        .execute()
    )


def _active_rows(user: AuthedUser, child_id: Optional[str]) -> List[Dict[str, Any]]:
    """ONE recipient's alert_record rows that are NOT dismissed (the active alerts).

    Filtered by user_id AND child_id, so the alerts list and the dashboard levels only
    ever see this recipient's alerts, never another recipient's pooled in. child_id None
    (no recipient yet) reads nothing (the query is skipped).

    BOUNDED (the every-list-is-capped rule): there is at most one active alert per chapter
    (the active-alert unique key is (user_id, child_id, chapter), migration 0010), so this
    read returns at most six rows and needs no cursor; it still carries a hard MAX_BOUNDED_ROWS
    `.limit(...)` as the runaway-read backstop. The cap is far above the six-chapter ceiling,
    so it never truncates an alert.
    """
    if child_id is None:
        return []
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(ALERT_RECORD_TABLE)
        .select("chapter, level, trigger_condition, dismissed, dismissed_level")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("dismissed", False)
        .limit(MAX_BOUNDED_ROWS)
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
    return parse_timestamptz(value)
