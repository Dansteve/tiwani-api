-- Migration 0003: activity_record (the LCE plan, stored) + RLS.
--
-- The activity_record is the stored output of the Life Continuity Engine
-- (Product.md section 4.4 step 8: "store the full activity record and confirm the
-- write before returning the plan"; the object is Product.md section 5 /
-- HardRules/Api/Modules/Models.md). One row per prepared activity, owned by a
-- user and tied to their care recipient. It is USER DATA (unlike the global
-- scenario_matrix / tag_modifier reference tables), so it is RLS user-scoped the
-- same way as child_profile (migration 0001): a user reads and writes only their
-- own rows. This is ADDITIVE: a new v3 table alongside the existing ones; nothing
-- here drops or alters another table.
--
-- The engine is server-side and deterministic; this table stores what it returned
-- (the base scores for audit, the final adjusted scores, the total, the tier, the
-- today flags that fed it, the ranked strategies, and the scheduled Pulse time) so
-- the dashboard can count activities per chapter (Task 4 wiring) and the Pulse /
-- LCI (Tasks 6/7) can read back the recommended tier.
--
-- Schema is owned by these migrations only (no create_all, no live table edits).
-- gen_random_uuid() is core Postgres (Supabase runs 15+); no extension needed.

-- =====================================================================
-- activity_record
-- One prepared activity (an LCE run) for a user's care recipient.
-- =====================================================================
create table if not exists public.activity_record (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,
    child_id            uuid not null references public.child_profile (id) on delete cascade,

    -- The activity this plan is for. chapter is one of the six fixed codes;
    -- activity_code is the scenario key (or a custom activity code). activity_name
    -- is the resolved human label (seeded name, or a readable custom label).
    chapter             text not null check (
                            chapter in ('school', 'career', 'family', 'social', 'travel', 'culture')
                        ),
    activity_code       text not null,
    activity_name       text not null,
    activity_date       date,

    -- The section 4.4 step 1 base scores (each 1..5), stored for audit so a plan
    -- can be explained after the fact (what the activity scored before the
    -- multiplier and modifiers).
    base_temporal       smallint not null check (base_temporal between 1 and 5),
    base_sensory        smallint not null check (base_sensory between 1 and 5),
    base_logistical     smallint not null check (base_logistical between 1 and 5),
    base_human          smallint not null check (base_human between 1 and 5),

    -- The final adjusted scores (section 4.4 step 4 output, each capped at 5).
    temporal            smallint not null check (temporal between 1 and 5),
    sensory             smallint not null check (sensory between 1 and 5),
    logistical          smallint not null check (logistical between 1 and 5),
    human               smallint not null check (human between 1 and 5),

    -- The total (4..20) and the recomputed tier (section 4.4 steps 5/6). The total
    -- must equal the sum of the four final cells (a stored-consistency guard).
    total               smallint not null check (total between 4 and 20),
    tier                text not null check (tier in ('Full', 'Modified', 'Pivot')),

    -- The section 4.4 "today" flags that fed step 4 (TG- codes), stored so the run
    -- is reproducible and the plan is explainable. Permanent profile tags live on
    -- child_profile; only the day-level flags are recorded per activity.
    today_flags         text[] not null default '{}',

    -- The ranked strategies the plan returned (section 4.4 step 7), stored as JSON
    -- (an ordered array of {title, detail, also_worked_in_chapter}). This is the
    -- list the app rendered; the canonical seed strategies stay in scenario_strategy.
    strategies          jsonb not null default '[]'::jsonb,

    -- Optional free text the Coordinator added (section 5). STORED ONLY: the engine
    -- and the LCI never read it (the structured-data-only rule, Models.md).
    context_note        text,

    -- The scheduled Post-Activity Pulse time (section 4.4 step 9: activity date
    -- + 2 hours, or 09:00 the next day if no date). The Pulse itself is Task 6;
    -- this column persists when it is due.
    scheduled_pulse_at  timestamptz not null,

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    -- The stored final cells must sum to the stored total (consistency guard).
    constraint activity_record_total_is_sum
        check (temporal + sensory + logistical + human = total)
);

-- Scope/count queries by owner and by chapter: the dashboard counts a user's
-- activities per chapter and reads the most recent prepared timestamp.
create index if not exists idx_activity_record_user_chapter
    on public.activity_record (user_id, chapter);

create index if not exists idx_activity_record_child
    on public.activity_record (child_id);

-- updated_at maintenance: reuse the shared trigger function from migration 0001
-- (public.set_updated_at) so the database keeps the timestamp honest.
drop trigger if exists trg_activity_record_updated_at on public.activity_record;
create trigger trg_activity_record_updated_at
    before update on public.activity_record
    for each row
    execute function public.set_updated_at();

-- =====================================================================
-- Row Level Security
-- activity_record is user data: a user may select, insert, update, and delete
-- only rows they own (user_id = auth.uid()). The with check on insert/update
-- prevents writing or moving a row to another owner. Same pattern as
-- child_profile (migration 0001). RLS is the database backstop; the service also
-- scopes every query by user_id (the first line).
-- =====================================================================
alter table public.activity_record enable row level security;

drop policy if exists activity_record_select_own on public.activity_record;
create policy activity_record_select_own
    on public.activity_record
    for select
    using (auth.uid() = user_id);

drop policy if exists activity_record_insert_own on public.activity_record;
create policy activity_record_insert_own
    on public.activity_record
    for insert
    with check (auth.uid() = user_id);

drop policy if exists activity_record_update_own on public.activity_record;
create policy activity_record_update_own
    on public.activity_record
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists activity_record_delete_own on public.activity_record;
create policy activity_record_delete_own
    on public.activity_record
    for delete
    using (auth.uid() = user_id);
