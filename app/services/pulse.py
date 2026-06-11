"""Pulse recording + pending data service (v3).

The layer between the Pulse routes and Supabase for the post-activity check-in
(Product.md section 4.7). It records the pulse_record, then (within 10 seconds, the
section 4.7 step) recomputes the chapter LCI and writes a snapshot via the LCI
service. The Erosion Alert evaluation (step 3) and the Strategy outcome counts
(step 4) are Tasks 7 and 9; their hooks are noted where they slot in.

The recommended TIER and the CHAPTER the LCI adjustment keys on are read from the
stored activity_record (the Pulse hard rule: never re-derive the tier). One pulse
per activity is a hard invariant: a second submit for the same activity is a 409
(AlreadyPulsedError), the database UNIQUE on activity_id being the backstop.

User scoping and RLS (HardRules/Api/Modules/Auth.md): every read and write runs
through get_anon_client(user.access_token); the activity_record lookup is RLS-scoped,
so an activity_id the caller does not own simply is not found (404 at the route),
never another user's row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.models.pulse import PendingPulse, PulseRecord
from app.services import lci as lci_service
from app.services.profile import _first, _rows

ACTIVITY_RECORD_TABLE = "activity_record"
PULSE_RECORD_TABLE = "pulse_record"

# The outcomes that close a Pulse for the "pending" query: an activity is no longer
# pending once any pulse exists for it (a completed Well/Okay/Difficult, OR a skipped
# one after the app's dismiss-twice). The pending list is simply activities past due
# with no pulse_record row at all.


class ActivityNotFoundError(Exception):
    """Raised when the activity_id is unknown or not the caller's (route maps to 404)."""


class AlreadyPulsedError(Exception):
    """Raised when a Pulse already exists for the activity (route maps to 409)."""


def record_pulse(
    user: AuthedUser,
    *,
    activity_id: str,
    outcome_code: str,
    challenge_dimension: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PulseRecord:
    """Record a Pulse for an activity, then recompute that chapter's LCI.

    Steps (section 4.7), in order:
      0. fetch the caller's activity_record (RLS-scoped). Unknown/not-owned =>
         ActivityNotFoundError (404). Read the STORED chapter + tier from it.
      1. reject a duplicate: a Pulse already recorded for this activity =>
         AlreadyPulsedError (409). One pulse per activity (section 4.7).
      2. INSERT the pulse_record (outcome, challenge dimension, the stored tier +
         chapter, timestamp) and confirm the write.
      3. recompute the chapter LCI and write a snapshot (lci_service), within 10s.
         (Task 7 alert evaluation and Task 9 strategy counts slot in after this.)
      4. return the stored PulseRecord the app renders.

    now is injectable for tests (the snapshot's taken_at); it defaults to UTC now and
    is the only clock the flow uses.
    """
    base_now = _utc_now(now)
    activity = _get_owned_activity(user, activity_id)
    if activity is None:
        raise ActivityNotFoundError("No such activity for this user")

    if _existing_pulse(user, activity_id) is not None:
        raise AlreadyPulsedError("A pulse already exists for this activity")

    chapter = activity.get("chapter")
    tier_recommended = activity.get("tier")

    stored = _insert_pulse(
        user,
        activity_id=activity_id,
        chapter=chapter,
        tier_recommended=tier_recommended,
        outcome_code=outcome_code,
        challenge_dimension=challenge_dimension,
        now=base_now,
    )

    # Section 4.7 step 2: recompute the chapter LCI and snapshot it (within 10s). The
    # alert evaluation (step 3, Task 7) and the strategy outcome counts (step 4,
    # Task 9) hook in here, after the LCI is current.
    lci_service.recompute_chapter_lci(user, chapter, now=base_now)

    return _to_pulse_record(stored, chapter=chapter, tier_recommended=tier_recommended)


def list_pending_pulses(user: AuthedUser, *, now: Optional[datetime] = None) -> List[PendingPulse]:
    """The activities whose scheduled Pulse time has passed with no pulse yet.

    The in-app prompt source (section 4.7): an activity is pending when its
    scheduled_pulse_at is at or before now AND no pulse_record exists for it (neither
    a completed nor a skipped one). Reads the caller's activity_record rows and their
    pulse_record activity ids under RLS, filters in Python, and returns each as a
    PendingPulse, soonest-due first. The app owns the persist-across-opens and
    dismiss-twice behaviour; the api only reports what is still pending.
    """
    base_now = _utc_now(now)
    client = get_anon_client(user.access_token)

    activities = _rows(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("id, activity_name, chapter, scheduled_pulse_at")
        .eq("user_id", user.id)
        .execute()
    )
    pulsed_ids = _pulsed_activity_ids(user)

    pending: List[PendingPulse] = []
    for row in activities:
        activity_id = row.get("id")
        scheduled_at = _parse_dt(row.get("scheduled_pulse_at"))
        if activity_id is None or scheduled_at is None:
            continue
        if str(activity_id) in pulsed_ids:
            continue
        if scheduled_at > base_now:
            continue
        pending.append(
            PendingPulse(
                activity_id=str(activity_id),
                activity_name=row.get("activity_name") or "",
                chapter=row.get("chapter"),
                scheduled_at=scheduled_at,
            )
        )
    pending.sort(key=lambda p: p.scheduled_at)
    return pending


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------


def _get_owned_activity(user: AuthedUser, activity_id: str) -> Optional[Dict[str, Any]]:
    """The caller's activity_record by id (chapter + tier), or None if not theirs.

    RLS scopes the read to the caller, so a forged id for another user matches
    nothing. Selects the stored chapter and tier the Pulse copies (never re-derived).
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(ACTIVITY_RECORD_TABLE)
        .select("id, chapter, tier")
        .eq("id", activity_id)
        .eq("user_id", user.id)
        .execute()
    )


def _existing_pulse(user: AuthedUser, activity_id: str) -> Optional[Dict[str, Any]]:
    """The existing pulse_record for an activity (the one-per-activity guard), or None."""
    client = get_anon_client(user.access_token)
    return _first(
        client.table(PULSE_RECORD_TABLE)
        .select("id")
        .eq("user_id", user.id)
        .eq("activity_id", activity_id)
        .execute()
    )


def _insert_pulse(
    user: AuthedUser,
    *,
    activity_id: str,
    chapter: str,
    tier_recommended: str,
    outcome_code: str,
    challenge_dimension: Optional[str],
    now: datetime,
) -> Dict[str, Any]:
    """Insert the pulse_record and return the stored row (write confirmed).

    user_id is the session; chapter and tier_recommended are the STORED activity
    values (copied, not re-derived). If the insert returns no representation, the row
    is read back under RLS so the record is confirmed before the recompute runs.
    """
    client = get_anon_client(user.access_token)
    insert_row = {
        "user_id": user.id,
        "activity_id": activity_id,
        "chapter": chapter,
        "tier_recommended": tier_recommended,
        "outcome_code": outcome_code,
        "challenge_dimension": challenge_dimension,
    }
    created = _first(client.table(PULSE_RECORD_TABLE).insert(insert_row).execute())
    if created is not None:
        return created
    # No representation returned on insert: read the row back under RLS (the full
    # row, so the returned record carries the db-assigned id and created_at) before
    # the recompute runs, so the Pulse is only ever returned once it is stored.
    confirmed = _first(
        client.table(PULSE_RECORD_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .eq("activity_id", activity_id)
        .execute()
    )
    if confirmed is None:
        raise RuntimeError("pulse_record write could not be confirmed")
    return confirmed


def _pulsed_activity_ids(user: AuthedUser) -> set:
    """The set of activity ids that already have a pulse (completed or skipped)."""
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(PULSE_RECORD_TABLE).select("activity_id").eq("user_id", user.id).execute()
    )
    return {str(r.get("activity_id")) for r in rows if r.get("activity_id") is not None}


# ---------------------------------------------------------------------------
# shaping
# ---------------------------------------------------------------------------


def _to_pulse_record(stored: Dict[str, Any], *, chapter: str, tier_recommended: str) -> PulseRecord:
    """Shape a stored pulse row into the PulseRecord the app renders.

    timestamp is the stored created_at (the instant recorded). challenge_dimension is
    null when not picked. chapter and tier_recommended come from the stored activity
    values (passed in), matching what was written.
    """
    timestamp = _parse_dt(stored.get("created_at")) or _utc_now(None)
    return PulseRecord(
        id=str(stored.get("id")),
        activity_id=str(stored.get("activity_id")),
        outcome_code=stored.get("outcome_code"),
        challenge_dimension=stored.get("challenge_dimension"),
        tier_recommended=tier_recommended,
        chapter=chapter,
        timestamp=timestamp,
    )


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
