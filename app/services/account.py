"""Account self-service data service (v3): export, soft-delete, reactivation.

The thin data layer behind the self-service account routes (GET /api/v3/me/export,
POST /api/v3/me/delete, GET /api/v3/me/account-status, POST /api/v3/me/reactivate) and the
soft-delete access block. It owns the Supabase reads and writes for a Coordinator acting on
their OWN account.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every function takes the
resolved AuthedUser and runs through get_anon_client(user.access_token), so PostgREST
carries the user's JWT and Row Level Security filters every query to that user's rows. The
export therefore CANNOT return another user's data: each per-table select is RLS-scoped to
the caller (and additionally filtered by user_id, the first line), so a row that is not the
caller's is physically unreachable.

Soft-delete + reactivation (migration 0013): "deleting" an account is a SOFT delete with a
single RECOVERY WINDOW. It sets user_profile.deleted_at = now(); the data is RETAINED, not
scrubbed, for RECOVERY_WINDOW_DAYS (90 days). Within that window the user can REACTIVATE by
simply signing back in (reactivate_account clears deleted_at). At 90 days the data is
PERMANENTLY deleted; that hard delete is a MANUAL / operational step (no automated purge job
runs here, the operational purge query is documented in supabase/README.md). The
hard-delete-due moment is COMPUTED as deleted_at + 90 days wherever needed (account_status);
there is no second column. The current-user dependency reads deleted_at via is_account_deleted
and rejects a closed account with 410, so a soft-deleted user can neither read nor write the
rest of the api until they reactivate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.services.timestamps import parse_timestamptz

logger = logging.getLogger(__name__)

USER_PROFILE_TABLE = "user_profile"

# The single recovery window: after a soft delete the account is recoverable (reactivatable by
# signing back in) for this many days; after it, the data is due for the manual/operational hard
# delete (no automated job). account_status computes hard_delete_due_at = deleted_at + this and
# reactivate_account refuses past it. One constant so the window lives in exactly one place.
RECOVERY_WINDOW_DAYS = 90

# The user-owned tables the export gathers, each RLS-scoped to the caller by user_id. These
# are exactly the rows that belong to one Coordinator: their profile, their care recipients,
# and the records keyed to them (activities, pulses, LCI snapshots, alerts, cards). The
# read-only seed/knowledge tables (scenario_matrix, scenario_strategy, tag_modifier) are
# shared reference data, not the user's data, so they are deliberately not exported.
CHILD_PROFILE_TABLE = "child_profile"
# The Continuity Card table. Named because soft_delete_account revokes the caller's active
# cards on closure (the same revoked_at marker the public token resolver checks), not only the
# export reading it.
CARD_RECORD_TABLE = "card_record"
_USER_OWNED_RECORD_TABLES = (
    "activity_record",
    "pulse_record",
    "lci_snapshot",
    "alert_record",
    CARD_RECORD_TABLE,
)


def _rows(response: Any) -> List[Dict[str, Any]]:
    """Return the list of rows from a Supabase execute() response.

    Mirrors app/services/profile._rows: .data is a list for a plain select, a single dict
    (or None) for a .single()/.maybe_single() read. Normalised to a list so callers handle
    one shape.
    """
    data = getattr(response, "data", None)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def _first(response: Any) -> Optional[Dict[str, Any]]:
    rows = _rows(response)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# soft-delete state (the access block)
# ---------------------------------------------------------------------------


class AccountPurgedError(Exception):
    """Raised when a reactivation is attempted past the 90-day recovery window (route -> 410).

    The account was soft-deleted more than RECOVERY_WINDOW_DAYS ago, so its data is due for
    (or already past) the manual/operational hard delete. Reactivation is no longer offered:
    the route maps this to 410 Gone (the data is gone / due to be purged).
    """


def _parse_deleted_at(value: Any) -> Optional[datetime]:
    """Parse user_profile.deleted_at (ISO string or datetime) to an aware UTC datetime, or None.

    Supabase returns timestamptz as an ISO string (sometimes with a trailing Z). The window
    math (now() vs deleted_at + 90 days) needs an aware datetime, so this normalises both the
    string and datetime shapes; a naive value is assumed UTC. Mirrors the parser in
    app/services/cards._parse_dt. None / unparseable reads as "no deletion timestamp".
    """
    return parse_timestamptz(value)


def _read_deleted_at(user: AuthedUser) -> Any:
    """Read the caller's OWN user_profile.deleted_at under RLS (the raw value or None).

    The single source the closure state reads from: eq id == user.id under the caller's token,
    so it can only ever see the caller's flag. Returns the raw column value (an ISO string when
    set) or None when the account is active, when there is no profile row yet, or when the read
    itself fails.

    Fail-open by design. The select is wrapped so that ANY failure to read deleted_at returns
    None, i.e. the account is treated as ACTIVE (not deleted). The two failure shapes this
    tolerates are a missing column (the deleted_at column not yet added by migration 0013 on a
    database where it has not been applied: PostgREST hard-errors on a select of a non-existent
    column, it does NOT quietly omit the key) and a transient read error (a Supabase blip).
    Either way the caught exception is logged at WARNING so the failure is observable, not
    silently swallowed, and None is returned.

    Rationale: soft-delete is a NON-security policy, not an access boundary. The data is
    RETAINED on closure and RLS still scopes every read to the caller, so reading deleted_at is
    only deciding whether to show the "account closed" block, never whether the caller may see
    another user's data. On a read failure, availability wins: a soft-delete read must NEVER be
    able to 500 the entire authenticated api (this read runs in get_current_user on EVERY data
    request, so an error here would otherwise take down every authenticated endpoint). The worst
    case of failing open is that a just-closed account briefly stays usable until the read
    recovers, which is strictly safer than locking every user out.

    is_account_deleted and account_status both build on this so the read (and its fail-open
    policy) lives in one place.
    """
    client = get_anon_client(user.access_token)
    try:
        row = _first(
            client.table(USER_PROFILE_TABLE)
            .select("deleted_at")
            .eq("id", user.id)
            .maybe_single()
            .execute()
        )
    except Exception:  # noqa: BLE001 - a soft-delete read must never 500 the whole api; fail open.
        logger.warning(
            "Could not read user_profile.deleted_at; treating account as active (fail-open)",
            exc_info=True,
        )
        return None
    if row is None:
        return None
    return row.get("deleted_at")


def is_account_deleted(user: AuthedUser) -> bool:
    """True when the caller's account is closed (user_profile.deleted_at is set).

    The check behind the current-user dependency's 410 block. It reads ONLY the caller's
    own user_profile row under RLS (eq id == user.id, the anon client carrying the caller's
    token), so it can never see another user's flag. A user with no profile row yet (a fresh
    sign-up before get_or_create_profile runs) is treated as active (returns False): there is
    nothing closed yet. The column is migration 0013; if the read fails (the column not yet
    applied, or a transient error) _read_deleted_at fails open and returns None, so this reads
    as active rather than 500-ing the request (see _read_deleted_at for the rationale).

    Note this is purely "is the flag set", independent of the 90-day recovery window: a
    soft-deleted account stays blocked on normal routes (410) for the whole window, until it
    reactivates (deleted_at cleared) or is hard-deleted.
    """
    return _read_deleted_at(user) is not None


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def export_account(user: AuthedUser) -> Dict[str, Any]:
    """Return a JSON-serialisable document of the caller's OWN data (RLS-scoped).

    The data behind GET /api/v3/me/export. It gathers, under the caller's token, every row
    that belongs to them: the user_profile row, their child_profile rows, and the
    user-owned records (activity_record, pulse_record, lci_snapshot, alert_record,
    card_record). Each select runs through the RLS-scoped anon client AND filters by
    user_id, so two independent guards (RLS + the explicit filter) make another user's rows
    unreachable; the export can only ever contain the caller's data.

    Shape: {"user_profile": <row|null>, "child_profile": [...], "activity_record": [...],
    ...}. The profile is a single object (one row per user) or null if none exists yet;
    every other key is a list (possibly empty). The values are the raw Supabase rows
    (PostgREST already returns JSON-native types), so the route can hand this straight to a
    JSON response for download.
    """
    client = get_anon_client(user.access_token)

    profile = _first(
        client.table(USER_PROFILE_TABLE).select("*").eq("id", user.id).maybe_single().execute()
    )

    document: Dict[str, Any] = {USER_PROFILE_TABLE: profile}
    document[CHILD_PROFILE_TABLE] = _rows(
        client.table(CHILD_PROFILE_TABLE).select("*").eq("user_id", user.id).execute()
    )
    for table in _USER_OWNED_RECORD_TABLES:
        document[table] = _rows(
            client.table(table).select("*").eq("user_id", user.id).execute()
        )
    return document


# ---------------------------------------------------------------------------
# soft-delete
# ---------------------------------------------------------------------------


def soft_delete_account(user: AuthedUser) -> Dict[str, Any]:
    """Close the caller's account: set user_profile.deleted_at = now() (SOFT delete) + revoke cards.

    The write behind POST /api/v3/me/delete. It is a SOFT delete: the row is NOT removed and
    no child data is scrubbed; the account is marked closed and the data is RETAINED for the
    90-day recovery window (RECOVERY_WINDOW_DAYS). It is recoverable: the user can reactivate
    by signing back in within 90 days (reactivate_account). After 90 days the data is
    permanently deleted by a manual/operational purge (no automated job). The update is
    RLS-scoped to the caller's own row (eq id == user.id under the caller's token), so it can
    only ever close the caller's own account.

    It ALSO revokes the caller's shared Continuity Cards (see _revoke_active_cards): a card is
    resolvable PUBLICLY by token with no auth, so a closed account's still-live share links
    would keep exposing the care recipient's data. Revoking them (the same revoked_at marker
    the public token resolver already checks, migration 0008) kills every active share link the
    instant the account closes. Reactivation leaves them revoked (the user re-shares).

    Idempotent: deleted_at is set to now() with no "only if null" guard, so a repeat call on
    an already-closed account simply refreshes the timestamp and still succeeds (the route
    depends on get_current_user_allow_deleted, so the closure block does not pre-empt a
    second delete). Returns {"deleted": True, "deleted_at": <iso>} for the route's
    confirmation; deleted_at is read back from the updated row so the response carries the
    canonical server timestamp.
    """
    client = get_anon_client(user.access_token)
    # now() is applied server-side by Postgres ("now()" is not available here), so we send a
    # marker and let the update set the column; PostgREST does not evaluate SQL functions in
    # an update payload, so we set an explicit UTC timestamp instead and return what stuck.
    now = datetime.now(timezone.utc)
    deleted_at = now.isoformat()
    updated = _first(
        client.table(USER_PROFILE_TABLE)
        .update({"deleted_at": deleted_at})
        .eq("id", user.id)
        .execute()
    )
    # Revoke the caller's active share links so a closed account stops exposing the recipient's
    # data publicly. Done after the account is marked closed; RLS-scoped to the caller's cards.
    _revoke_active_cards(user, revoked_at=now)
    confirmed_at = (updated or {}).get("deleted_at", deleted_at)
    return {"deleted": True, "deleted_at": confirmed_at}


def _revoke_active_cards(user: AuthedUser, *, revoked_at: datetime) -> None:
    """Soft-revoke the caller's still-active Continuity Cards (set revoked_at = now()).

    REUSES the existing card revoke mechanism rather than inventing a second one: the public
    token read (public.get_card_by_token, migration 0008) returns a card only when
    revoked_at is null, so setting revoked_at marks the card revoked and the share link dies
    immediately. This is the same column app/services/cards.revoke_card sets for a single card;
    here it is applied in bulk to every one of the caller's cards that is not already revoked.

    RLS-scoped and caller-only: the update runs under the caller's token and filters
    user_id == user.id, so it can only ever touch the caller's own cards. It additionally
    filters revoked_at is null, so an already-revoked card is left untouched (its original
    revoke timestamp is preserved, the audit row is never rewritten). No representation is
    requested; a caller with no cards simply matches no rows. Best-effort within the closure:
    the account is already marked closed before this runs.
    """
    client = get_anon_client(user.access_token)
    client.table(CARD_RECORD_TABLE).update({"revoked_at": revoked_at.isoformat()}).eq(
        "user_id", user.id
    ).is_("revoked_at", "null").execute()


# ---------------------------------------------------------------------------
# account status + reactivation (the 90-day recovery window)
# ---------------------------------------------------------------------------


def account_status(user: AuthedUser) -> Dict[str, Any]:
    """The caller's closure state + the computed 90-day recovery window (no write).

    The data behind GET /api/v3/me/account-status, how the app learns post-login that the
    account is closed so it can offer reactivation. Reads the caller's OWN
    user_profile.deleted_at under RLS (eq id == user.id) and returns:

      {
        "deleted":            bool,         # deleted_at is set
        "deleted_at":         iso | None,   # when it was closed
        "hard_delete_due_at": iso | None,   # COMPUTED: deleted_at + 90 days (None if active)
        "reactivatable":      bool,         # deleted AND now() < hard_delete_due_at
      }

    hard_delete_due_at is computed here (deleted_at + RECOVERY_WINDOW_DAYS), never stored.
    reactivatable is True only inside the window: a closed account whose 90 days have elapsed
    is past recovery (its data is due for the manual purge), so reactivatable is False even
    though deleted is True. An active account returns deleted False and both timestamps None.
    """
    raw = _read_deleted_at(user)
    deleted_at = _parse_deleted_at(raw)
    if deleted_at is None:
        return {
            "deleted": False,
            "deleted_at": None,
            "hard_delete_due_at": None,
            "reactivatable": False,
        }
    due_at = deleted_at + timedelta(days=RECOVERY_WINDOW_DAYS)
    reactivatable = datetime.now(timezone.utc) < due_at
    return {
        "deleted": True,
        "deleted_at": deleted_at.isoformat(),
        "hard_delete_due_at": due_at.isoformat(),
        "reactivatable": reactivatable,
    }


def reactivate_account(user: AuthedUser) -> Dict[str, Any]:
    """Reactivate the caller's soft-deleted account within the 90-day window (clears deleted_at).

    The write behind POST /api/v3/me/reactivate. Reactivation is simply signing back in: this
    clears user_profile.deleted_at on the caller's OWN row (RLS-scoped, eq id == user.id under
    the caller's token, so it can only ever reactivate the caller's own account), after which
    the current-user dependency stops returning 410 and the account is live again.

    Three cases:
      - soft-deleted AND within 90 days -> clear deleted_at, return {"reactivated": True}.
      - soft-deleted but PAST 90 days   -> raise AccountPurgedError (route -> 410): the data is
        due for / past the manual hard delete, so reactivation is no longer offered. deleted_at
        is left untouched so the account stays closed and purge-eligible.
      - NOT deleted (already active)    -> idempotent success, {"reactivated": True}, no write.
        Chosen over a 400 because the app only offers reactivation when status says deleted, so
        a reactivate on an already-active account is a benign race (e.g. reactivated in another
        tab); a calm success is friendlier than an error and is covered by a test.

    Cards revoked at deletion are deliberately NOT un-revoked here: reactivation restores the
    account, and the user re-shares any card they still want live (the public links stay dead).
    """
    raw = _read_deleted_at(user)
    deleted_at = _parse_deleted_at(raw)
    if deleted_at is None:
        # Already active: nothing to clear, idempotent success.
        return {"reactivated": True}

    due_at = deleted_at + timedelta(days=RECOVERY_WINDOW_DAYS)
    if datetime.now(timezone.utc) >= due_at:
        raise AccountPurgedError("This account is past its recovery window")

    client = get_anon_client(user.access_token)
    client.table(USER_PROFILE_TABLE).update({"deleted_at": None}).eq("id", user.id).execute()
    return {"reactivated": True}
