-- Migration 0002: the LCE seed tables (scenario matrix + tag architecture) + RLS.
--
-- These hold the TIWANI-derived v1 Knowledge Base (the scenario base scores +
-- ranked strategies) and Tag Architecture (the per-tag dimension modifiers) that
-- the Life Continuity Engine reads (Product.md section 4.4,
-- HardRules/Api/Modules/SeedData.md, Engine.md). The engine reads these rows; it
-- never hardcodes a score. They are ADDITIVE: new v3 reference tables alongside
-- the prototype's tables; nothing here drops or alters a prototype table.
--
-- GLOBAL REFERENCE DATA, NOT USER DATA. Unlike user_profile / child_profile, these
-- rows are the SAME for every user (the scenario matrix and the tag modifiers are
-- product content, not a user's data). So the RLS model is different on purpose:
-- RLS is still enabled on every table (the hard rule: no table without RLS), but
-- the policy grants READ to any authenticated user and grants NO write to users.
-- Writes happen only through the versioned seed loader run with the service-role
-- key (which bypasses RLS), so the content can change only as a deliberate,
-- versioned seed step owned by the PRODUCT OWNER, never by an end user.
--
-- VERSIONED. seed_version stamps every row with the source version
-- (knowledge_base_v1, tag_architecture_v1). A score or modifier change is a NEW
-- version loaded as a new seed step, not an in-place edit (SeedData.md).
--
-- PROVENANCE. The v1 values are authored from the shared four-dimension rubric and
-- are labelled "TIWANI-derived v1, pending owner ratification + clinical sign-off"
-- (the seed sources carry the rationale per cell). The owner can change any cell.
--
-- Schema is owned by these migrations only (no create_all, no live table edits).

-- =====================================================================
-- scenario_matrix
-- One row per (chapter, activity): the four base scores (each 1..5) the LCE
-- step 1 looks up. A custom activity with no row falls back to the chapter
-- average (handled in the engine, not here).
-- =====================================================================
create table if not exists public.scenario_matrix (
    id                  uuid primary key default gen_random_uuid(),
    seed_version        text not null,
    chapter             text not null check (
                            chapter in ('school', 'career', 'family', 'social', 'travel', 'culture')
                        ),
    activity_code       text not null,
    activity_name       text not null,
    temporal            smallint not null check (temporal between 1 and 5),
    sensory             smallint not null check (sensory between 1 and 5),
    logistical          smallint not null check (logistical between 1 and 5),
    human               smallint not null check (human between 1 and 5),
    rationale           text not null,
    created_at          timestamptz not null default now(),
    -- One scenario per (chapter, activity_code) within a seed version.
    unique (seed_version, chapter, activity_code)
);

create index if not exists idx_scenario_matrix_lookup
    on public.scenario_matrix (seed_version, chapter, activity_code);

-- =====================================================================
-- scenario_strategy
-- The ranked starter strategies for a scenario (LCE step 7 starter order). One
-- row per (scenario, rank); rank is 1-based and 1 is shown first.
-- =====================================================================
create table if not exists public.scenario_strategy (
    id                  uuid primary key default gen_random_uuid(),
    scenario_id         uuid not null references public.scenario_matrix (id) on delete cascade,
    rank                smallint not null check (rank >= 1),
    title               text not null,
    body                text not null,
    created_at          timestamptz not null default now(),
    -- No two strategies share a rank within one scenario.
    unique (scenario_id, rank)
);

create index if not exists idx_scenario_strategy_scenario
    on public.scenario_strategy (scenario_id);

-- =====================================================================
-- tag_modifier
-- One row per (tag_code, dimension): the +1/+2 a tag adds to a dimension (LCE
-- step 3). A tag affecting two dimensions has two rows. A 0-pressure tag (every
-- Recovery RC- tag) has NO row. The engine caps the SUM of tag contributions per
-- dimension at +2 at apply time; this stores only the individual +1/+2.
-- =====================================================================
create table if not exists public.tag_modifier (
    id                  uuid primary key default gen_random_uuid(),
    seed_version        text not null,
    tag_code            text not null,
    dimension           text not null check (
                            dimension in ('temporal', 'sensory', 'logistical', 'human')
                        ),
    modifier            smallint not null check (modifier between 1 and 2),
    rationale           text not null,
    created_at          timestamptz not null default now(),
    -- One modifier per (tag_code, dimension) within a seed version.
    unique (seed_version, tag_code, dimension)
);

create index if not exists idx_tag_modifier_lookup
    on public.tag_modifier (seed_version, tag_code);

-- =====================================================================
-- Row Level Security
-- These are GLOBAL reference tables (the same content for every user), so the
-- model is read-for-all-authenticated, write-for-none. RLS is still enabled on
-- every table (no table without RLS). There is intentionally NO insert/update/
-- delete policy: the seed loader writes with the service-role key (RLS bypassed),
-- so only a deliberate versioned seed step can change the content, never a user.
-- =====================================================================

alter table public.scenario_matrix enable row level security;

drop policy if exists scenario_matrix_read_authenticated on public.scenario_matrix;
create policy scenario_matrix_read_authenticated
    on public.scenario_matrix
    for select
    to authenticated
    using (true);

alter table public.scenario_strategy enable row level security;

drop policy if exists scenario_strategy_read_authenticated on public.scenario_strategy;
create policy scenario_strategy_read_authenticated
    on public.scenario_strategy
    for select
    to authenticated
    using (true);

alter table public.tag_modifier enable row level security;

drop policy if exists tag_modifier_read_authenticated on public.tag_modifier;
create policy tag_modifier_read_authenticated
    on public.tag_modifier
    for select
    to authenticated
    using (true);
