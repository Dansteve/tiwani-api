-- Migration 0014: strategy_library_item (the Strategy Library, Product.md section 4.10) + RLS.
--
-- !!! PENDING OWNER APPLY: NOT applied to production (orchestrator-gated, the 0013 banner
-- convention). Apply this only on the owner's go-ahead, alongside the rest of the Task 9
-- merge. Until applied, the auto-save / promotion / suppression / cross-context reads have no
-- table to act on, so the api treats a missing library row as "no learning yet" and the plan
-- still returns the seeded starter strategies (the engine never depends on this table). !!!
--
-- WHAT IT IS. The learning layer (Product.md section 4.10, HardRules/Api/Modules/Strategies.md):
-- every strategy that appears in a completed plan is saved automatically, tagged to its chapter
-- and scenario, PER CARE RECIPIENT, with positive/negative outcome counts and a per-scenario
-- soft, reversible suppressed marker. Over time a strategy is PROMOTED (ranked first),
-- SUPPRESSED (excluded), or surfaced ACROSS chapters. These flags drive the LCE step 7 ranking
-- ORDER only; they never change a score, total, tier, or the LCI (those stay deterministic and
-- section 4.4 / 4.8 exact).
--
-- PER-RECIPIENT. Like activity_record / pulse_record / card_record, a library item belongs to
-- EXACTLY ONE recipient (user_id + child_id). A row for child A never affects child B's ranking
-- or counts (the isolation rule, Docs/FeatureDecisions.md). The unique key is
-- (user_id, child_id, chapter, scenario_type, title) so the auto-save UPSERT is idempotent on a
-- re-plan of the same scenario (the same strategy is saved once per recipient + scenario, its
-- counts accumulate across plans).
--
-- This is USER DATA, RLS user-scoped exactly like activity_record (migration 0003): a user
-- selects / inserts / updates / deletes only their own rows (auth.uid() = user_id). The
-- with-check on insert/update prevents writing or moving a row to another owner. ADDITIVE: a new
-- table alongside the existing ones; it drops or alters nothing. gen_random_uuid() is core
-- Postgres (Supabase 15+); no extension needed.

-- =====================================================================
-- strategy_library_item
-- One saved strategy for a user's care recipient, tagged to a chapter + scenario, with the
-- learning counts and the reversible per-scenario suppression marker.
-- =====================================================================
create table if not exists public.strategy_library_item (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,
    child_id            uuid not null references public.child_profile (id) on delete cascade,

    -- The scenario this strategy was saved from. chapter is one of the six fixed codes;
    -- scenario_type is the activity_code (the scenario key). Suppression and promotion are
    -- specific to (child_id, chapter, scenario_type): a strategy suppressed in one scenario can
    -- still appear in another (section 4.10).
    chapter             text not null check (
                            chapter in ('school', 'career', 'family', 'social', 'travel', 'culture')
                        ),
    scenario_type       text not null,

    -- The strategy identity (the seeded strategy text, carried verbatim). title is the short
    -- label the plan ranks on; description is the one-line outsider-actionable body (section 4.6
    -- voice). The title is the stable identity within a scenario (the seed ranks are 1..N with no
    -- duplicate title in a scenario).
    title               text not null,
    description         text not null default '',

    -- The dimensions this strategy matches, derived from its scenario's HIGH base dimensions
    -- (base score >= 3) at save time. Cross-context surfacing offers the strategy in OTHER
    -- chapters when one of these tags is a high-scoring dimension of the target activity
    -- (section 4.4 step 7 / section 4.10). Stored as the dimension codes (temporal/sensory/
    -- logistical/human).
    dimension_tags      text[] not null default '{}',

    -- The learning counts (section 4.10, equal attribution: a pulse outcome is applied equally to
    -- every strategy in that plan). positive_count is Well/Okay outcomes, negative_count is
    -- Difficult; a skipped pulse moves neither.
    positive_count      integer not null default 0 check (positive_count >= 0),
    negative_count      integer not null default 0 check (negative_count >= 0),

    -- Promotion is DERIVED (positive_count >= 2 AND positive_count > negative_count); this column
    -- caches it so a read can rank without recomputing, and is kept in step with the counts on
    -- every outcome update. It is never the source of truth (the counts are).
    promoted            boolean not null default false,

    -- Suppression (section 4.10): a strategy removed 3 times for the same scenario is excluded
    -- next time. removal_count counts the removals for THIS (child_id, chapter, scenario_type);
    -- suppressed is the soft, REVERSIBLE marker the ranker reads. The Coordinator re-allows by
    -- clearing suppressed and resetting removal_count to 0, so it takes another 3 removals to
    -- re-suppress (reversible by design).
    removal_count       integer not null default 0 check (removal_count >= 0),
    suppressed          boolean not null default false,

    -- Cross-context dismissal (section 4.10: "dismissible per chapter"). The set of chapter codes
    -- in which the Coordinator has dismissed this strategy's "Also worked in [chapter]" surfacing,
    -- so a dismissed cross-context suggestion does not reappear in that chapter.
    cross_context_dismissed_chapters text[] not null default '{}',

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    -- One library item per (recipient, scenario, strategy): the auto-save UPSERT target, so a
    -- re-plan of the same scenario does not duplicate a strategy (its counts accumulate instead).
    constraint strategy_library_item_identity_unique
        unique (user_id, child_id, chapter, scenario_type, title)
);

-- The ranker reads a recipient's items for one (chapter, scenario_type) to apply promotion +
-- suppression; this index matches that scope.
create index if not exists idx_strategy_library_item_scope
    on public.strategy_library_item (user_id, child_id, chapter, scenario_type);

-- Cross-context surfacing scans a recipient's promoted/successful items across chapters; this
-- index matches the per-recipient cross-chapter scan.
create index if not exists idx_strategy_library_item_child
    on public.strategy_library_item (child_id);

-- updated_at maintenance: reuse the shared trigger function from migration 0001
-- (public.set_updated_at) so the database keeps the timestamp honest.
drop trigger if exists trg_strategy_library_item_updated_at on public.strategy_library_item;
create trigger trg_strategy_library_item_updated_at
    before update on public.strategy_library_item
    for each row
    execute function public.set_updated_at();

-- =====================================================================
-- Row Level Security
-- strategy_library_item is user data: a user may select, insert, update, and delete only rows
-- they own (user_id = auth.uid()). The with check on insert/update prevents writing or moving a
-- row to another owner. Same pattern as activity_record (migration 0003). RLS is the database
-- backstop; the service also scopes every query by user_id (and child_id for the isolation rule).
-- =====================================================================
alter table public.strategy_library_item enable row level security;

drop policy if exists strategy_library_item_select_own on public.strategy_library_item;
create policy strategy_library_item_select_own
    on public.strategy_library_item
    for select
    using (auth.uid() = user_id);

drop policy if exists strategy_library_item_insert_own on public.strategy_library_item;
create policy strategy_library_item_insert_own
    on public.strategy_library_item
    for insert
    with check (auth.uid() = user_id);

drop policy if exists strategy_library_item_update_own on public.strategy_library_item;
create policy strategy_library_item_update_own
    on public.strategy_library_item
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists strategy_library_item_delete_own on public.strategy_library_item;
create policy strategy_library_item_delete_own
    on public.strategy_library_item
    for delete
    using (auth.uid() = user_id);
