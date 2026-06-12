-- Migration 0011: pulse_record + child_id (the per-recipient pulse history) + backfill.
--
-- !!! APPLIED TO PRODUCTION 2026-06-12 (orchestrated go-live; backfill verified, 0 nulls) !!!
-- Part of the Multi Care Recipient backend (Docs/FeatureDecisions.md, the design note).
-- It has been applied to the production database in the orchestrated multi-recipient
-- go-live (with 0009 and 0010; 0009 and 0011 add child_id to the two history tables, 0010
-- swaps the alert unique key); the backfill from each pulse's own activity_record was
-- verified (every pulse_record row carries a non-null child_id). The one-recipient guard is
-- lifted and the plan POST carries child_id. The code is also unit-tested against the fake
-- Supabase client.
--
-- WHY THIS EXISTS (a deliberate addition to the design note's two-migration list):
-- the design note names the lci_snapshot and alert_record migrations, because those are
-- where the LANDMINE was framed. But the Life Continuity Index (section 4.8) is FOLDED
-- from pulse_record, and pulse_record (migration 0004) is keyed by (user_id, chapter)
-- only, with no child_id (the chapter is copied from the activity, the recipient is not).
-- So a per-recipient LCI fold cannot scope pulses to one recipient from pulse_record
-- alone: two recipients' pulses for the same chapter would pool into one fold, exactly
-- the mix the isolation rule forbids. A pulse provably belongs to ONE recipient (its
-- activity's child_id), so storing that on the pulse is correct, not speculative, and it
-- makes pulse_record consistent with activity_record / card_record, which already carry
-- child_id. The alternative (scoping every pulse read through a join to activity_record)
-- would add an id-set filter to every fold; a direct child_id column is the same clean
-- .eq("child_id", ...) the snapshots and alerts use. This is the "done right" path the
-- design note asks for. Flagged for the owner in the report as an addition to the two
-- listed migrations.
--
-- IDEMPOTENT and ADDITIVE: add-column / create-index are `if (not) exists`; the backfill
-- is a guarded UPDATE that only fills NULLs from the pulse's own activity_record. It drops
-- or alters no other object.
--
-- NULLABILITY: child_id is added NULLABLE so the backfill runs on existing rows first.
-- The service writes it on every new pulse (it has the activity's child_id in hand), so
-- new rows are never null; a follow-up migration sets NOT NULL once the backfill is
-- verified (see the note at the end).

-- =====================================================================
-- pulse_record.child_id
-- The care recipient this pulse is for, copied from the pulse's activity_record at
-- record time (the same recipient the activity belongs to). Nullable for the backfill;
-- cascade so deleting a recipient removes their pulse history, matching activity_record.
-- =====================================================================
alter table public.pulse_record
    add column if not exists child_id uuid
        references public.child_profile (id) on delete cascade;

-- The LCI fold reads a user's pulses per recipient, per chapter. This index matches the
-- per-recipient scope; the old (user_id, chapter) index is kept (it still serves a
-- child-agnostic scan; dropping it is not required for correctness).
create index if not exists idx_pulse_record_user_child_chapter
    on public.pulse_record (user_id, child_id, chapter);

-- =====================================================================
-- Backfill: set child_id on every legacy pulse from its OWN activity_record.
--
-- Unlike the lci_snapshot / alert_record backfills (which infer the sole child), a
-- pulse's recipient is KNOWN exactly: pulse_record.activity_id -> activity_record.child_id
-- (activity_record has carried child_id NOT NULL since migration 0003). So this fills
-- child_id from the precise owning activity, not by inference. Guarded so a re-run is
-- safe: only rows where child_id is still null are touched, and the join is on the
-- pulse's own activity within the same user (a pulse and its activity always share the
-- owner), so a pulse is only ever filled with its own recipient.
-- =====================================================================
update public.pulse_record p
set child_id = a.child_id
from public.activity_record a
where p.child_id is null
  and p.activity_id = a.id
  and p.user_id = a.user_id;

-- =====================================================================
-- After this is applied AND the backfill is verified on production (every pulse_record
-- row has a non-null child_id, which the activity join guarantees since activity_record
-- always has one), a follow-up migration should:
--     alter table public.pulse_record alter column child_id set not null;
-- It is deliberately NOT done here so applying 0011 cannot fail mid-backfill. RLS is
-- unchanged: the existing pulse_record_*_own policies (migration 0004) already scope
-- every row to auth.uid() = user_id, and child_id is always one of the caller's own
-- children, so no policy change is needed.
-- =====================================================================
