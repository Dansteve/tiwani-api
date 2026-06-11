-- Migration 0004: pulse_record + lci_snapshot (the Pulse and the LCI history) + RLS.
--
-- Two USER-DATA tables for the post-activity Pulse (Product.md section 4.7) and the
-- Life Continuity Index (section 4.8, AUTHORITATIVE), the objects in section 5 /
-- HardRules/Api/Modules/Models.md. Both are RLS user-scoped the same way as
-- child_profile / activity_record (migrations 0001 / 0003): a user reads and writes
-- only their own rows. ADDITIVE: new v3 tables; nothing here drops or alters another.
--
-- pulse_record: one recorded Pulse per prepared activity. The outcome (Well / Okay /
-- Difficult, or skipped after a Pulse is dismissed twice) plus the activity's STORED
-- recommended tier and chapter (copied here from the activity_record so the LCI fold
-- reads a stable triple and never re-derives the tier). One pulse per activity is a
-- hard invariant, so activity_id is UNIQUE: a second submit for the same activity is
-- rejected at the database, the backstop to the route's 409.
--
-- lci_snapshot: the per-chapter LCI score over time. The weekly trajectory (section
-- 4.8: compare to the score 7 days prior) and the Task 7 alert rule ("chapter LCI
-- declining for 3 weekly snapshots in a row") read this history. A snapshot is
-- written whenever a chapter's score changes (on each pulse), so the 7-days-prior
-- look-back always has a recorded point; the formal weekly cadence is a Task 7 cron
-- on top of the same table.
--
-- Schema is owned by these migrations only (no create_all, no live table edits).
-- gen_random_uuid() is core Postgres (Supabase runs 15+); no extension needed.

-- =====================================================================
-- pulse_record
-- One recorded Pulse for a user's prepared activity (section 4.7).
-- =====================================================================
create table if not exists public.pulse_record (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,

    -- The prepared activity this Pulse answers. UNIQUE: one Pulse per activity
    -- (section 4.7); a second submit is a 409 at the route and is rejected here too.
    -- On the activity_record being deleted, its pulse goes with it.
    activity_id         uuid not null unique
                            references public.activity_record (id) on delete cascade,

    -- The chapter and the recommended tier are COPIED from the activity_record at
    -- record time (the stored values, section 4.8 / Pulse.md): the LCI fold reads
    -- this triple (outcome x tier) and never re-derives the tier. chapter is one of
    -- the six fixed codes; tier is the LCE's recomputed tier for that plan.
    chapter             text not null check (
                            chapter in ('school', 'career', 'family', 'social', 'travel', 'culture')
                        ),
    tier_recommended    text not null check (tier_recommended in ('Full', 'Modified', 'Pivot')),

    -- The two-tap outcome (section 4.7). 'skipped' is the recorded state after the
    -- Pulse is dismissed twice: a real row with a 0 LCI adjustment, never a penalty.
    outcome_code        text not null check (
                            outcome_code in ('well', 'okay', 'difficult', 'skipped')
                        ),

    -- The optional "main challenge" dimension (the second question). Stored only; it
    -- never feeds the score (only outcome x tier does, the structured-data rule).
    -- Null when the Coordinator did not pick one (or for a skipped pulse).
    challenge_dimension text check (
                            challenge_dimension in ('temporal', 'sensory', 'logistical', 'human')
                        ),

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- Scope/aggregate queries by owner and by chapter: the LCI reads a user's pulses
-- per chapter, in time order, to fold the score.
create index if not exists idx_pulse_record_user_chapter
    on public.pulse_record (user_id, chapter);

create index if not exists idx_pulse_record_activity
    on public.pulse_record (activity_id);

-- updated_at maintenance: reuse the shared trigger from migration 0001.
drop trigger if exists trg_pulse_record_updated_at on public.pulse_record;
create trigger trg_pulse_record_updated_at
    before update on public.pulse_record
    for each row
    execute function public.set_updated_at();

-- =====================================================================
-- lci_snapshot
-- A per-chapter LCI score at a point in time (section 4.8 trajectory history).
-- =====================================================================
create table if not exists public.lci_snapshot (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users (id) on delete cascade,

    -- The chapter this snapshot scores, and the whole-number 0 to 100 index then.
    chapter     text not null check (
                    chapter in ('school', 'career', 'family', 'social', 'travel', 'culture')
                ),
    score       smallint not null check (score between 0 and 100),

    -- The instant this score held. The weekly trajectory compares the current score
    -- to the latest snapshot at or before (now - 7 days); the Task 7 alert rule
    -- walks the weekly history. Defaults to now() (a snapshot is written as a chapter
    -- score changes).
    taken_at    timestamptz not null default now(),

    created_at  timestamptz not null default now()
);

-- The trajectory and the alert rule read a user's chapter history newest-first.
create index if not exists idx_lci_snapshot_user_chapter_taken
    on public.lci_snapshot (user_id, chapter, taken_at desc);

-- =====================================================================
-- Row Level Security
-- Both tables are user data: a user may select, insert, update, and delete only
-- rows they own (user_id = auth.uid()). The with check on insert/update prevents
-- writing or moving a row to another owner. Same pattern as activity_record
-- (migration 0003). RLS is the database backstop; the service scopes every query by
-- user_id (the first line). lci_snapshot is append-only in practice (no update
-- path), but the policy set is kept symmetric for safety.
-- =====================================================================
alter table public.pulse_record enable row level security;

drop policy if exists pulse_record_select_own on public.pulse_record;
create policy pulse_record_select_own
    on public.pulse_record
    for select
    using (auth.uid() = user_id);

drop policy if exists pulse_record_insert_own on public.pulse_record;
create policy pulse_record_insert_own
    on public.pulse_record
    for insert
    with check (auth.uid() = user_id);

drop policy if exists pulse_record_update_own on public.pulse_record;
create policy pulse_record_update_own
    on public.pulse_record
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists pulse_record_delete_own on public.pulse_record;
create policy pulse_record_delete_own
    on public.pulse_record
    for delete
    using (auth.uid() = user_id);

alter table public.lci_snapshot enable row level security;

drop policy if exists lci_snapshot_select_own on public.lci_snapshot;
create policy lci_snapshot_select_own
    on public.lci_snapshot
    for select
    using (auth.uid() = user_id);

drop policy if exists lci_snapshot_insert_own on public.lci_snapshot;
create policy lci_snapshot_insert_own
    on public.lci_snapshot
    for insert
    with check (auth.uid() = user_id);

drop policy if exists lci_snapshot_update_own on public.lci_snapshot;
create policy lci_snapshot_update_own
    on public.lci_snapshot
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists lci_snapshot_delete_own on public.lci_snapshot;
create policy lci_snapshot_delete_own
    on public.lci_snapshot
    for delete
    using (auth.uid() = user_id);
