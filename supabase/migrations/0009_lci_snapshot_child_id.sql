-- Migration 0009: lci_snapshot + child_id (the per-recipient LCI history) + backfill.
--
-- !!! APPLIED TO PRODUCTION 2026-06-12 (orchestrated go-live; backfill verified, 0 nulls) !!!
-- This file is part of the Multi Care Recipient backend (Docs/FeatureDecisions.md, the
-- design note). It has been applied to the production database (alongside 0010 and 0011)
-- in the orchestrated multi-recipient go-live; the sole-child backfill was verified (every
-- lci_snapshot row carries a non-null child_id). The one-recipient guard is lifted and the
-- plan POST now carries child_id, so every per-recipient read scopes to one named recipient.
-- The code is also unit-tested against the fake Supabase client. Applied with 0010 and 0011.
--
-- WHY: the Life Continuity Index (Product.md section 4.8, AUTHORITATIVE) is computed
-- and snapshotted PER CHAPTER, but the lci_snapshot table (migration 0004) is keyed by
-- (user_id, chapter) only. The moment a Coordinator has a second care recipient, two
-- people's snapshots for the same chapter share a series and the weekly trajectory
-- (and the Task 7 "declining 3 weekly snapshots" alert condition) mixes them. The
-- isolation rule (the board's law): every snapshot belongs to EXACTLY ONE named
-- recipient. This adds child_id so every snapshot read and write scopes to one child.
--
-- This mirrors activity_record (migration 0003), which already carries child_id with
-- a foreign key to child_profile and an on-delete cascade.
--
-- IDEMPOTENT and ADDITIVE: add-column / create-index are `if (not) exists`, the
-- backfill is a guarded UPDATE that only fills NULLs and only when the user has exactly
-- one child, and it drops or alters no other object.
--
-- NULLABILITY: child_id is added NULLABLE so the backfill can run on the existing rows
-- first (a NOT NULL add would reject them). A follow-up migration sets it NOT NULL once
-- every write path supplies child_id and the backfill has been verified on production
-- (see the note at the end). Until then the service always writes child_id on insert,
-- so new rows are never null; only historical rows rely on the backfill.

-- =====================================================================
-- lci_snapshot.child_id
-- The care recipient this snapshot scores. Nullable for the backfill (see above);
-- the service writes it on every new snapshot. Cascade so deleting a recipient
-- removes their snapshot history, matching activity_record.
-- =====================================================================
alter table public.lci_snapshot
    add column if not exists child_id uuid
        references public.child_profile (id) on delete cascade;

-- The trajectory and the alert rule read a user's chapter history per recipient,
-- newest-first. This index supersedes the (user_id, chapter, taken_at) one for the
-- per-recipient reads; the old index is kept (it still serves a child-agnostic scan and
-- dropping it is not required for correctness).
create index if not exists idx_lci_snapshot_user_child_chapter_taken
    on public.lci_snapshot (user_id, child_id, chapter, taken_at desc);

-- =====================================================================
-- Backfill: set child_id on every legacy snapshot to the user's SOLE existing child.
--
-- The one-recipient guard means every user has AT MOST one child today, so the legacy
-- snapshots can only belong to that one recipient. This fills child_id for rows written
-- before the column existed. It is guarded three ways so re-running it is safe and it
-- never guesses:
--   - only rows where child_id is still null are touched (re-run safe),
--   - only when the user has EXACTLY ONE child (count = 1), so a user who somehow has
--     more than one is left untouched for the owner to resolve by hand (never mixed),
--   - the child is matched by user_id, so a snapshot is only ever filled with that
--     user's own recipient.
-- =====================================================================
update public.lci_snapshot s
set child_id = sole.id
from (
    -- (array_agg(id))[1], not min(id): Postgres has no min(uuid); the having count(*) = 1
    -- guard means the array holds exactly one element, so [1] is that sole child's id.
    select user_id, (array_agg(id))[1] as id
    from public.child_profile
    group by user_id
    having count(*) = 1
) sole
where s.child_id is null
  and s.user_id = sole.user_id;

-- =====================================================================
-- After this is applied AND the backfill is verified on production (every lci_snapshot
-- row has a non-null child_id), a follow-up migration should:
--     alter table public.lci_snapshot alter column child_id set not null;
-- It is deliberately NOT done here so applying 0009 cannot fail on a pre-existing row
-- the backfill could not resolve (a user with more than one child, which the guard
-- prevents but the migration does not assume). RLS is unchanged: the existing
-- lci_snapshot_*_own policies (migration 0004) already scope every row to
-- auth.uid() = user_id, and child_id is always one of the caller's own children, so no
-- policy change is needed.
-- =====================================================================
