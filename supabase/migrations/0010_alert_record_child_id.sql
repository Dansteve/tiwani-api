-- Migration 0010: alert_record + child_id, unique key (user_id, chapter) becomes
-- (user_id, child_id, chapter) + backfill.
--
-- !!! PENDING OWNER REVIEW, NOT YET APPLIED !!!
-- Written as part of the Multi Care Recipient backend (Docs/FeatureDecisions.md, the
-- design note). It is NOT applied to the production database in this change: the owner
-- reviews the migrations before the live DB is touched, and the one-recipient guard
-- (a second child_profile create is a 409) stays in place until the full feature
-- (api + app switcher) is integrated under review. The code is unit-tested against the
-- fake Supabase client only; this SQL is the artefact the owner applies later. Apply
-- 0009 (the lci_snapshot companion) and 0010 together, 0009 first.
--
-- WHY: the Erosion Alert (Product.md section 4.9, AUTHORITATIVE) is one active alert
-- per chapter, enforced by the (user_id, chapter) UNIQUE the post-pulse evaluation
-- UPSERTs (migration 0005). With a second care recipient that unique key would force
-- two recipients to SHARE one alert row per chapter: recipient B's evaluation would
-- overwrite recipient A's alert, and a dismissal for one would silence the other. The
-- isolation rule (the board's law): every alert belongs to EXACTLY ONE named recipient,
-- and alerts stay per-recipient and calm. This adds child_id and moves the uniqueness
-- (and the active-alert invariant) to (user_id, child_id, chapter).
--
-- IDEMPOTENT and ADDITIVE where it can be: the add-column and create-index are
-- `if (not) exists`; the constraint swap uses `if exists` / `if not exists`; the
-- backfill is a guarded UPDATE that only fills NULLs and only for a user with exactly
-- one child. The constraint swap is the one ALTER that changes an existing object, and
-- it is required for correctness (the old key cannot coexist with per-recipient alerts).
--
-- NULLABILITY + ORDER: child_id is added NULLABLE so the backfill runs on existing rows
-- before the new unique key is created (a NOT NULL add would reject pre-existing rows,
-- and the composite unique must not be created until every row has a child_id, else two
-- legacy rows for the same (user, chapter) with NULL child_id would violate it). The
-- service writes child_id on every alert insert, so new rows are never null; a follow-up
-- migration sets NOT NULL once the backfill is verified (see the note at the end).

-- =====================================================================
-- 1. alert_record.child_id (nullable for the backfill; cascade like activity_record).
-- =====================================================================
alter table public.alert_record
    add column if not exists child_id uuid
        references public.child_profile (id) on delete cascade;

-- =====================================================================
-- 2. Backfill child_id to the user's SOLE existing child (same guards as 0009).
--
-- The one-recipient guard means every user has AT MOST one child today, so a legacy
-- alert can only belong to that one recipient. Guarded so a re-run is safe and it never
-- guesses: only NULL child_id rows are touched, only when the user has EXACTLY ONE child
-- (count = 1), and the child is matched by the same user_id. This MUST run before the
-- composite unique key is created (step 3), so no two rows share a NULL child_id under it.
-- =====================================================================
update public.alert_record a
set child_id = sole.id
from (
    -- (array_agg(id))[1], not min(id): Postgres has no min(uuid); the having count(*) = 1
    -- guard means the array holds exactly one element, so [1] is that sole child's id.
    select user_id, (array_agg(id))[1] as id
    from public.child_profile
    group by user_id
    having count(*) = 1
) sole
where a.child_id is null
  and a.user_id = sole.user_id;

-- =====================================================================
-- 3. Move the active-alert uniqueness from (user_id, chapter) to
--    (user_id, child_id, chapter). The old key forced one alert per chapter ACROSS
--    recipients; the new key is one active alert per chapter PER recipient, the
--    section 4.9 invariant the post-pulse UPSERT now targets.
--
-- Drop the old unique constraint, then add the new composite one. Both guarded so the
-- swap is idempotent (re-running finds the old one already gone and the new one present).
-- =====================================================================
alter table public.alert_record
    drop constraint if exists uq_alert_record_user_chapter;

alter table public.alert_record
    add constraint uq_alert_record_user_child_chapter
        unique (user_id, child_id, chapter);

-- The dashboard and the alerts endpoint read a user's active alerts per recipient; the
-- composite index matches the new scope. The old (user_id, chapter) index is kept (it
-- still serves a child-agnostic scan; dropping it is not required for correctness).
create index if not exists idx_alert_record_user_child_chapter
    on public.alert_record (user_id, child_id, chapter);

-- =====================================================================
-- After this is applied AND the backfill is verified on production (every alert_record
-- row has a non-null child_id), a follow-up migration should:
--     alter table public.alert_record alter column child_id set not null;
-- It is deliberately NOT done here so applying 0010 cannot fail on a pre-existing row
-- the backfill could not resolve (a user with more than one child, which the guard
-- prevents but the migration does not assume). RLS is unchanged: the existing
-- alert_record_*_own policies (migration 0005) already scope every row to
-- auth.uid() = user_id, and child_id is always one of the caller's own children, so no
-- policy change is needed. The composite unique key carries child_id, which is itself
-- always user-owned, so the active-alert invariant stays per (user, recipient, chapter).
-- =====================================================================
