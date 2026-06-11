-- Migration 0008: soft-revoke for the Continuity Card + a token read that dies the
-- instant a card is revoked OR expired.
--
-- The Card History feature (HardRules/Api/Modules/Cards.md) lets a Coordinator see
-- and MANAGE the cards they have generated. Managing includes taking a shared card
-- back: a "revoke" that kills the public link immediately. The expert-review board
-- required a SOFT revoke, not a hard delete: keep the card_record row as the audit
-- trail (who shared what, when) and mark it revoked, never DROP the row. So this
-- migration adds a nullable revoked_at timestamp (null = active, set = revoked) and
-- rebuilds the token read function so a revoked or expired token returns nothing.
--
-- ADDITIVE and idempotent: it only adds a nullable column to card_record (migration
-- 0007) and replaces the read function in place; it drops or alters no other object.
-- Schema is owned by this migration (no create_all, no live table edits).

-- =====================================================================
-- card_record.revoked_at
-- The soft-revoke marker. NULL means the card is active; a timestamp means the
-- Coordinator revoked it at that instant (the audit row is kept, never deleted).
-- Nullable with no default so every existing card stays active until revoked.
-- =====================================================================
alter table public.card_record
    add column if not exists revoked_at timestamptz;

-- =====================================================================
-- The token read path (no auth), rebuilt: get_card_by_token(token) -> content
--
-- Same SECURITY DEFINER contract as migration 0007 (it runs past RLS so an
-- UNAUTHENTICATED token holder can read exactly one card's SAFE content, never
-- user_id / child_id / activity_id / the token). Two changes here:
--
--   1. The WHERE now requires the card to be BOTH live (expires_at > now()) AND not
--      revoked (revoked_at is null). The instant a Coordinator revokes a card (sets
--      revoked_at), this function stops returning it, so the public link dies
--      immediately, the database backstop behind the app's revoke action.
--
--   2. The freshness signal (the clinical board's mandatory staleness finding: a card
--      is a point-in-time snapshot, so a stale card can hand a NEW helper outdated
--      strategies). The function merges two READ-TIME fields onto the safe content
--      jsonb so the helper's app can warn:
--        - generated_at: the card's created_at (the date it was prepared). A
--          timestamp, not PII, it is exactly the staleness signal the board asked to
--          surface.
--        - is_stale: computed AGAINST now() on every call (older than the 30-day
--          freshness window). It is computed here, never stored, so an old card
--          reports stale without the stored row being mutated. The 30-day interval is
--          the same threshold as the Python CARD_FRESHNESS_DAYS constant
--          (app/services/cards.py), which governs the same signal on the owner's list;
--          both are review-deferred to the psychiatrist card-copy sign-off.
--      Merging keeps the return type jsonb and exposes no owner id or foreign key: the
--      base content is already safe (first name only), and these two fields are a date
--      and a boolean derived from it.
--
-- search_path is pinned empty and every reference is schema-qualified (the standard
-- SECURITY DEFINER hardening); EXECUTE stays granted to anon and authenticated because
-- the share link is opened without a session.
-- =====================================================================
create or replace function public.get_card_by_token(p_token text)
returns jsonb
language sql
security definer
set search_path = ''
stable
as $$
    select c.content || jsonb_build_object(
               'generated_at', to_jsonb(c.created_at),
               'is_stale', (now() - c.created_at) > interval '30 days'
           )
    from public.card_record c
    where c.token = p_token
      and c.expires_at > now()
      and c.revoked_at is null;
$$;

-- The token read is reachable without a session (the helper has no account). Re-assert
-- the narrow grants after the replace: revoke the broad default, grant EXECUTE to the
-- anon and authenticated roles only.
revoke all on function public.get_card_by_token(text) from public;
grant execute on function public.get_card_by_token(text) to anon;
grant execute on function public.get_card_by_token(text) to authenticated;
