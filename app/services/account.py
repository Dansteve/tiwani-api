"""Account self-service data service (v3): export and soft-delete.

The thin data layer behind the two self-service account routes (GET /api/v3/me/export,
POST /api/v3/me/delete) and the soft-delete access block. It owns the Supabase reads and
writes for a Coordinator acting on their OWN account.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every function takes the
resolved AuthedUser and runs through get_anon_client(user.access_token), so PostgREST
carries the user's JWT and Row Level Security filters every query to that user's rows. The
export therefore CANNOT return another user's data: each per-table select is RLS-scoped to
the caller (and additionally filtered by user_id, the first line), so a row that is not the
caller's is physically unreachable.

Soft-delete (migration 0013): "deleting" an account is a SOFT delete. It sets
user_profile.deleted_at = now(); the data is RETAINED (5 years per the retention policy, then
hard-deleted MANUALLY, no automated job). The current-user dependency reads deleted_at via
is_account_deleted and rejects a closed account with 410, so a soft-deleted user can neither
read nor write the rest of the api.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client

USER_PROFILE_TABLE = "user_profile"

# The user-owned tables the export gathers, each RLS-scoped to the caller by user_id. These
# are exactly the rows that belong to one Coordinator: their profile, their care recipients,
# and the records keyed to them (activities, pulses, LCI snapshots, alerts, cards). The
# read-only seed/knowledge tables (scenario_matrix, scenario_strategy, tag_modifier) are
# shared reference data, not the user's data, so they are deliberately not exported.
CHILD_PROFILE_TABLE = "child_profile"
_USER_OWNED_RECORD_TABLES = (
    "activity_record",
    "pulse_record",
    "lci_snapshot",
    "alert_record",
    "card_record",
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


def is_account_deleted(user: AuthedUser) -> bool:
    """True when the caller's account is closed (user_profile.deleted_at is set).

    The check behind the current-user dependency's 410 block. It reads ONLY the caller's
    own user_profile row under RLS (eq id == user.id, the anon client carrying the caller's
    token), so it can never see another user's flag. A user with no profile row yet (a fresh
    sign-up before get_or_create_profile runs) is treated as active (returns False): there is
    nothing closed yet. The column is migration 0013; on a database where it has not been
    applied the row simply has no deleted_at key, which reads as active.
    """
    client = get_anon_client(user.access_token)
    row = _first(
        client.table(USER_PROFILE_TABLE)
        .select("deleted_at")
        .eq("id", user.id)
        .maybe_single()
        .execute()
    )
    if row is None:
        return False
    return row.get("deleted_at") is not None


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
    """Close the caller's account: set user_profile.deleted_at = now() (SOFT delete).

    The write behind POST /api/v3/me/delete. It is a SOFT delete: the row is NOT removed and
    no child data is touched; the account is marked closed and the data is RETAINED (5 years
    per policy, then hard-deleted manually, no automated job). The update is RLS-scoped to the
    caller's own row (eq id == user.id under the caller's token), so it can only ever close
    the caller's own account.

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
    from datetime import datetime, timezone

    deleted_at = datetime.now(timezone.utc).isoformat()
    updated = _first(
        client.table(USER_PROFILE_TABLE)
        .update({"deleted_at": deleted_at})
        .eq("id", user.id)
        .execute()
    )
    confirmed_at = (updated or {}).get("deleted_at", deleted_at)
    return {"deleted": True, "deleted_at": confirmed_at}
