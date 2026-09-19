-- Migration 0022: the Adapted tier rename + the scenario_moment reference table.
--
-- The DB-parity half of the PRD v2.0 / LCE Addendum reconciliation (Wave 1 Slice A,
-- BuildPlan-PRDv2.md; LCEEngineAddendum.md). Two additive/parity changes:
--
--   1. TIER RENAME. The middle participation route was renamed "Modified" -> "Adapted"
--      (Green -> Full, Amber -> Adapted, Red -> Pivot; Product2.md / Canonical Glossary
--      v1.0). This rewrites the stored tier value on every table that carries it and swaps
--      the CHECK constraint's allowed set. The engine already emits "Adapted".
--
--   2. scenario_moment. A reference table mirroring the Python-seed scenario moments the
--      Fusion Layer reads (LCEEngineAddendum.md section 1), for future DB parity. In Wave 1
--      the engine reads moments from the versioned Python seed (app/seed), so this table is
--      not yet on the engine read path; it lands here so the schema is ready when moments
--      move to the DB (Wave 2). Strategy PROVENANCE (source / derived_from / moment /
--      moment_label) needs NO column: it is stored inside the existing activity_record
--      .strategies jsonb, and the Specificity Gate is recomputed from it on read.
--
-- !!! NOT APPLIED (Wave 1 is a local, demonstrable slice; BuildPlan-PRDv2.md gate note).
-- The PRODUCTION apply is owner-gated (Decisions.md D12), like every other migration.
-- Wave 1 extends the PYTHON seed so the engine runs locally; this file is written for
-- parity and is NOT run against any database as part of this slice.

-- =====================================================================
-- 1. Tier rename: 'Modified' -> 'Adapted' on every table that stores a tier.
--    Order per table: relax the CHECK, rewrite the data, tighten the CHECK.
-- =====================================================================

-- scenario_matrix (seed reference data, migration 0002)
alter table public.scenario_matrix drop constraint if exists scenario_matrix_tier_check;
update public.scenario_matrix set tier = 'Adapted' where tier = 'Modified';
alter table public.scenario_matrix
    add constraint scenario_matrix_tier_check
    check (tier in ('Full', 'Adapted', 'Pivot'));

-- activity_record (the stored plan tier, migration 0003)
alter table public.activity_record drop constraint if exists activity_record_tier_check;
update public.activity_record set tier = 'Adapted' where tier = 'Modified';
alter table public.activity_record
    add constraint activity_record_tier_check
    check (tier in ('Full', 'Adapted', 'Pivot'));

-- pulse_record (the copied recommended tier, migration 0004)
alter table public.pulse_record
    drop constraint if exists pulse_record_tier_recommended_check;
update public.pulse_record set tier_recommended = 'Adapted' where tier_recommended = 'Modified';
alter table public.pulse_record
    add constraint pulse_record_tier_recommended_check
    check (tier_recommended in ('Full', 'Adapted', 'Pivot'));

-- =====================================================================
-- 2. scenario_moment: the Fusion Layer's scenario sub-moments (parity).
--    GLOBAL REFERENCE DATA (like scenario_matrix): RLS enabled, READ to any
--    authenticated user, NO user write (writes are the service-role seed loader
--    only). Versioned by seed_version. loads is the tag codes the moment loads.
-- =====================================================================
create table if not exists public.scenario_moment (
    id                  uuid primary key default gen_random_uuid(),
    seed_version        text not null,
    chapter             text not null,
    activity_code       text not null,
    moment_id           text not null,
    label               text not null,
    -- The tag codes whose pressure concentrates in this moment (SN-/TR-/CM-/RC-).
    loads               text[] not null default '{}',
    -- The moment's order within the scenario (0-based), so the ordered list is stable.
    position            smallint not null default 0,
    created_at          timestamptz not null default now(),
    -- One moment id per (scenario, seed version).
    unique (seed_version, chapter, activity_code, moment_id)
);

create index if not exists idx_scenario_moment_lookup
    on public.scenario_moment (seed_version, chapter, activity_code);

alter table public.scenario_moment enable row level security;

-- READ to any authenticated user; NO user write (service-role seed loader only).
drop policy if exists scenario_moment_select_authenticated on public.scenario_moment;
create policy scenario_moment_select_authenticated
    on public.scenario_moment for select
    to authenticated
    using (true);
