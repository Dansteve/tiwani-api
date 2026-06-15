"""Profile + care-recipient data service (v3).

The thin data layer the v3 profile/child/onboarding routes call. It owns the
Supabase reads and writes for the two foundation tables (user_profile,
child_profile) and the onboarding write. No engine logic lives here.

User scoping and RLS (HardRules/Api/Modules/Auth.md, Models.md): every function
takes the resolved AuthedUser and runs through get_anon_client(user.access_token),
so PostgREST carries the user's JWT and Row Level Security filters every query to
that user's rows. Cross-user access cannot return another user's row (RLS makes it
invisible), which surfaces as 404 at the route. The user_profile row is created on
first access by the AUTHENTICATED CALLER under RLS: migration 0006 adds an insert
policy "with check (auth.uid() = id)", so get_or_create_profile inserts the row
with the user's own token (no service-role key in the request path); id == user.id
means a profile can only be created for the caller.

Tables: public.user_profile (id == auth.users.id), public.child_profile (one
active care recipient per user for the MVP; user_id == auth.uid()).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.auth import AuthedUser
from app.db import get_anon_client
from app.services.pagination import MAX_BOUNDED_ROWS

USER_PROFILE_TABLE = "user_profile"
CHILD_PROFILE_TABLE = "child_profile"

logger = logging.getLogger(__name__)

# The 0015 substrate RPC that mints the creator's OWNER recipient_membership for a new
# recipient. Per-recipient sharing and the Village Hub key their reads on this owner row.
BOOTSTRAP_OWNER_FN = "bootstrap_recipient_owner"


class CareRecipientExistsError(Exception):
    """The interim one-recipient guard's error. RETAINED but no longer raised.

    This was raised by create_child while the interim one-recipient guard held
    (Docs/FeatureDecisions.md, multi care recipient): the dashboard, LCI, and alerts
    aggregated by user_id only, so a second child_profile would have pooled two people
    into one mixed resilience score (a Product.md section 4.8 / 4.9 correctness failure).
    Now that every per-recipient read and the plan POST are scoped by child_id, the guard
    is lifted and create_child no longer raises this. The type is kept (the POST /child
    route still catches it as a defensive 409) so a future re-introduction has a home and
    no caller breaks; it is simply never raised today.
    """


class ChildNotFoundError(Exception):
    """Raised when an explicit child_id is not one the caller owns (route -> 404).

    The per-recipient resolver (resolve_child_id) raises this when a caller names a
    child_id that is not theirs: RLS makes another user's child_profile invisible, so
    the ownership read returns nothing and we do not confirm whether the row exists.
    """


def _rows(response: Any) -> List[Dict[str, Any]]:
    """Return the list of rows from a Supabase execute() response.

    The supabase/postgrest client returns an APIResponse whose .data is a list
    for a plain select/insert/update, or a single dict (or None) when the query
    used .single()/.maybe_single(). This normalises both to a list so callers
    handle one shape.
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
# user_profile
# ---------------------------------------------------------------------------


def get_or_create_profile(user: AuthedUser, first_name: Optional[str] = None) -> Dict[str, Any]:
    """Return the caller's user_profile row, creating it on first access.

    The profile row is keyed to the Supabase Auth user id (id == auth.uid()).
    A first read uses the RLS-scoped anon client; if no row exists yet (the app
    signs the user up via the Supabase Auth SDK, so the api may see a user before
    a profile row exists), it is created by the caller under RLS (the insert
    policy, migration 0006). first_name is required by the table; when the caller does not supply
    one we fall back to the email local-part, then to "Coordinator", so the
    create never violates the not-null constraint.
    """
    client = get_anon_client(user.access_token)
    existing = _first(
        client.table(USER_PROFILE_TABLE).select("*").eq("id", user.id).maybe_single().execute()
    )
    if existing is not None:
        return existing

    resolved_first_name = first_name or _default_first_name(user)
    insert_row = {
        "id": user.id,
        "email": user.email,
        "first_name": resolved_first_name,
    }
    # The authenticated caller inserts their OWN profile row under RLS
    # (user_profile_insert_own, "with check (auth.uid() = id)", migration 0006).
    # No service-role key in the request path; id == user.id, so a profile can
    # only ever be created for the caller.
    created = _first(
        client.table(USER_PROFILE_TABLE).insert(insert_row).execute()
    )
    if created is not None:
        return created
    # Some PostgREST configs return no representation on insert; read it back
    # under RLS to return the canonical row (with the db defaults + timestamps).
    return _first(
        client.table(USER_PROFILE_TABLE).select("*").eq("id", user.id).single().execute()
    ) or insert_row


def update_profile(user: AuthedUser, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update the caller's profile with the given fields; return the updated row.

    fields is already the validated, set-only subset (the route builds it from
    UserProfileUpdate). RLS limits the update to the caller's own row; an empty
    fields dict is handled at the route (nothing to do). Returns None if no row
    matched (the caller does not own a profile row), which the route maps to 404.
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(USER_PROFILE_TABLE).update(fields).eq("id", user.id).execute()
    )


def _default_first_name(user: AuthedUser) -> str:
    if user.email and "@" in user.email:
        local = user.email.split("@", 1)[0].strip()
        if local:
            return local
    return "Coordinator"


# ---------------------------------------------------------------------------
# child_profile (general care recipient, D8)
# ---------------------------------------------------------------------------


def get_child(user: AuthedUser) -> Optional[Dict[str, Any]]:
    """Return the caller's most-recent care recipient, or None if none exists yet.

    A caller may now have several recipients; this returns the most recently created
    one (the newest). RLS scopes the read to the caller's rows, so it can never surface
    another user's recipient.

    This is the DEFAULT-CHILD reader: resolve_child_id and prepare_plan call it when no
    explicit child_id is named (the back-compat default, so a client that sends none reads
    that one recipient), and the onboarding write still uses it to decide create-vs-update.
    """
    client = get_anon_client(user.access_token)
    rows = _rows(
        client.table(CHILD_PROFILE_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return rows[0] if rows else None


def list_children(user: AuthedUser) -> List[Dict[str, Any]]:
    """The caller's care recipients, newest first (RLS-scoped).

    The read behind GET /api/v1/children, the list the app switcher reads to offer the
    active recipient. The select filters by user_id and runs under the caller's token, so
    Row Level Security makes another user's recipients physically unreachable: this can
    only ever return the caller's own children. Ordered by created_at descending so the
    newest recipient is first. Now that the one-recipient guard is lifted, this returns
    every recipient the caller has created (the switcher's full list).

    BOUNDED (the every-list-is-capped rule): a Coordinator manages a small set of care
    recipients, so this list needs no cursor; the read still carries a hard MAX_BOUNDED_ROWS
    `.limit(...)` so a pathological row count can never make the query or the switcher list
    unbounded. The cap is well above any real recipient count, so it never truncates data.
    """
    client = get_anon_client(user.access_token)
    return _rows(
        client.table(CHILD_PROFILE_TABLE)
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .limit(MAX_BOUNDED_ROWS)
        .execute()
    )


def get_child_by_id(user: AuthedUser, child_id: str) -> Optional[Dict[str, Any]]:
    """The caller's care recipient by id (RLS-scoped), or None if not theirs.

    Filters by id AND user_id under the caller's token, so RLS plus the explicit
    user_id filter make another user's recipient unreachable: a forged child_id matches
    nothing and returns None. The ownership check behind resolve_child_id.
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(CHILD_PROFILE_TABLE)
        .select("*")
        .eq("id", child_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )


def resolve_child_id(user: AuthedUser, child_id: Optional[str] = None) -> Optional[str]:
    """Resolve WHICH care recipient a per-recipient read/write is for (the chokepoint).

    The per-recipient chokepoint that replaces "just read the sole child". Every
    per-recipient read (the dashboard, LCI, alerts) and the post-pulse recompute resolves
    the target child_id through this, so the isolation rule (one named recipient per
    read, never a mix) holds in one place:

      - child_id given: VERIFY the caller owns it (get_child_by_id under RLS). If they do,
        return it; if not, raise ChildNotFoundError (the route maps to 404). A caller can
        never address another user's recipient, even by guessing an id.
      - child_id omitted: fall back to the caller's most-recent child (get_child). This is
        the back-compat default so existing clients that send no child_id keep working; with
        several recipients now allowed, a client should send the active child_id explicitly
        (the dashboard/LCI/alerts/plan paths pass the switcher's active recipient).
      - no child at all: return None (a fresh user with no recipient yet); the callers
        treat None as "no data" and return the empty/not-started baseline.
    """
    if child_id is not None:
        owned = get_child_by_id(user, child_id)
        if owned is None:
            raise ChildNotFoundError("No care recipient found for this id")
        return owned["id"]
    sole = get_child(user)
    return sole["id"] if sole is not None else None


def _bootstrap_owner_membership(client: Any, child_row: Dict[str, Any]) -> None:
    """Mint the creator's OWNER recipient_membership for a freshly created recipient.

    The 0015 substrate keys per-recipient sharing and the Village Hub on an owner
    membership row: without it the creator is not a "member" of their own recipient, so the
    membership-scoped reads (the village board, the share roster) return them nothing.
    bootstrap_recipient_owner is idempotent (it reuses an existing active owner row) and
    owner-checked at the DB (it requires child_profile.user_id == auth.uid()).

    Best-effort by design: the recipient is already created, so a transient bootstrap
    failure must NOT fail creation (which, with no child-insert idempotency, would risk a
    duplicate recipient on retry). A failure is logged and the owner row can be backfilled;
    it never propagates.
    """
    child_id = child_row.get("id") if isinstance(child_row, dict) else None
    if not child_id:
        return
    try:
        client.rpc(BOOTSTRAP_OWNER_FN, {"p_child_id": child_id}).execute()
    except Exception:  # noqa: BLE001 - best-effort; creation must not fail on the mint
        logger.warning("bootstrap_recipient_owner failed for recipient %s", child_id)


def create_child(user: AuthedUser, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a care recipient for the caller and return the row.

    user_id is set from the authenticated session, never from the client; the
    RLS insert policy additionally requires user_id == auth.uid(), so a row can
    only be created for the caller. tags Enum values are coerced to their string
    codes for storage.

    Multiple recipients are supported (Docs/FeatureDecisions.md, the multi care
    recipient design note): the interim one-recipient guard that rejected a second
    create is lifted now that every per-recipient read (dashboard, LCI, alerts) and
    the plan POST are scoped by child_id, so two recipients can no longer pool into
    one mixed resilience score. complete_onboarding still calls this only when
    get_child(user) is None (otherwise it updates), so onboarding stays a single
    recipient per user; the app's Settings/switcher is what adds further recipients.
    """
    client = get_anon_client(user.access_token)
    insert_row = {**_serialize_child_fields(fields), "user_id": user.id}
    created = _first(client.table(CHILD_PROFILE_TABLE).insert(insert_row).execute())
    if created is None:
        # Fall back to reading back the freshly created row under RLS.
        created = get_child(user) or insert_row
    _bootstrap_owner_membership(client, created)
    return created


def update_child(
    user: AuthedUser, child_id: str, fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Update the caller's care recipient by id; return the updated row or None.

    RLS scopes the update to the caller's own row, so a forged child_id for
    another user matches nothing (returns None, which the route maps to 404).
    """
    client = get_anon_client(user.access_token)
    return _first(
        client.table(CHILD_PROFILE_TABLE)
        .update(_serialize_child_fields(fields))
        .eq("id", child_id)
        .eq("user_id", user.id)
        .execute()
    )


# ---------------------------------------------------------------------------
# onboarding write
# ---------------------------------------------------------------------------


def complete_onboarding(user: AuthedUser, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the onboarding submission once: upsert the recipient + mark done.

    payload is the validated, serialized OnboardingPayload (name, age_band,
    support_level_code, tags as string codes; the first_activity selection is
    carried for the app's routing and is NOT scored or persisted as an
    activity_record here, that is Task 5). Steps:
      1. ensure the user_profile row exists (get-or-create),
      2. create the care recipient if the user has none, else update it (one
         active recipient per user for the MVP; an edit applies to plans only,
         section 4.11, so this never rewrites historical records),
      3. set user_profile.onboarding_complete = true.
    Returns {"profile": <row>, "child": <row>}. All writes are RLS-scoped to the
    caller (the profile-complete flip and the recipient write), except the
    one deliberate service-role profile create inside get_or_create_profile.
    """
    child_fields = {
        "name": payload["name"],
        "age_band": payload.get("age_band"),
        "support_level_code": payload.get("support_level_code"),
        "tags": payload.get("tags", []),
    }

    get_or_create_profile(user, first_name=None)

    existing_child = get_child(user)
    if existing_child is None:
        child = create_child(user, child_fields)
    else:
        child = update_child(user, existing_child["id"], child_fields) or existing_child

    profile = update_profile(user, {"onboarding_complete": True})
    if profile is None:
        # The profile row was just ensured above; read it back under RLS so the
        # response always carries the canonical profile.
        profile = get_or_create_profile(user, first_name=None)

    return {"profile": profile, "child": child}


def _serialize_child_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce Enum values (SupportLevelCode, Tag) to their string codes.

    The route passes pydantic-validated values; Supabase stores plain strings
    and a text[] for tags. Enum members serialize to their .value; lists of Tag
    members become a list of code strings. Other values pass through unchanged.
    """
    serialized: Dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, list):
            serialized[key] = [getattr(item, "value", item) for item in value]
        else:
            serialized[key] = getattr(value, "value", value)
    return serialized
