-- Migration 0013: user_profile soft-delete column (account closure, retained 5 years).
--
-- Adds `deleted_at timestamptz null` to public.user_profile so a Coordinator can CLOSE
-- their account (POST /api/v3/me/delete) without the data being hard-deleted. Per the
-- retention policy the data is RETAINED for 5 YEARS; the actual hard deletion is done
-- MANUALLY after that window (there is no automated purge job). A null deleted_at means
-- the account is active; a non-null deleted_at means it is closed (soft-deleted) and the
-- api treats the user as gone (the current-user path rejects a soft-deleted account with
-- 410, so a closed account can neither read nor write).
--
-- ADDITIVE and IDEMPOTENT: `add column if not exists` only appends a nullable column;
-- it does not alter or drop anything and changes no existing row (every current row gets
-- deleted_at = null, i.e. active). No RLS change is needed: the existing
-- user_profile_select_own / user_profile_update_own policies (migration 0001) already scope
-- the column to the owner (auth.uid() = id), so the caller reads and sets their OWN
-- deleted_at under RLS, never anyone else's.
--
-- PENDING OWNER APPLY: this migration is written but NOT applied to production by this
-- change. The orchestrator/owner applies it (the same posture as migration 0012's deferred
-- follow-ups). Until it is applied, the /me/delete write and the soft-delete access block
-- have no column to act on.

-- =====================================================================
-- user_profile.deleted_at
-- Null = active account. Non-null = closed (soft-deleted), retained per policy.
-- =====================================================================
alter table public.user_profile
    add column if not exists deleted_at timestamptz;
