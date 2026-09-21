-- Migration 0022: the Adapted tier rename + the scenario_moment reference table.
--
-- Applied ZERO-DOWNTIME in TWO phases (2026-09-21). A one-shot rewrite+tighten would 500 the
-- still-live pre-rename api during the deploy rollover: its Tier enum has no 'Adapted' and no
-- _missing_ shim, so it cannot READ an 'Adapted' row, and after a straight tighten it cannot
-- WRITE its 'Modified'. The split keeps BOTH the old and the new api working throughout:
--
--   PHASE A ("0022a", below): WIDEN the tier CHECK to accept BOTH 'Modified' and 'Adapted',
--     and create scenario_moment. Run BEFORE deploying the new api. The old api keeps
--     writing/reading 'Modified' (still allowed); the incoming api can write 'Adapted'.
--     APPLIED to prod 2026-09-21 (Supabase migration 0022a_fusion_transitional_...).
--
--   PHASE B ("0022b", below): REWRITE 'Modified' -> 'Adapted' and TIGHTEN the CHECK to the
--     final ('Full','Adapted','Pivot'). Run ONLY AFTER the new api is live, so no old
--     instance is left to read an 'Adapted' value its enum does not know. PENDING until the
--     api deploy lands.
--
-- scenario_moment mirrors the Python-seed scenario moments the Fusion Layer reads
-- (LCEEngineAddendum.md section 1), for future DB parity. In Wave 1 the engine reads moments
-- from the Python seed (app/seed), so this table is not yet on the engine read path; it lands
-- here so the schema is ready when moments move to the DB (Wave 2). Strategy PROVENANCE needs
-- NO column: it is stored inside activity_record.strategies jsonb, and the Specificity Gate
-- is recomputed from it on read.

-- =====================================================================
-- PHASE A (0022a): widen the CHECK + create scenario_moment. APPLIED to prod 2026-09-21.
-- =====================================================================

alter table public.scenario_matrix drop constraint if exists scenario_matrix_tier_check;
alter table public.scenario_matrix
    add constraint scenario_matrix_tier_check
    check (tier in ('Full', 'Modified', 'Adapted', 'Pivot'));

alter table public.activity_record drop constraint if exists activity_record_tier_check;
alter table public.activity_record
    add constraint activity_record_tier_check
    check (tier in ('Full', 'Modified', 'Adapted', 'Pivot'));

alter table public.pulse_record drop constraint if exists pulse_record_tier_recommended_check;
alter table public.pulse_record
    add constraint pulse_record_tier_recommended_check
    check (tier_recommended in ('Full', 'Modified', 'Adapted', 'Pivot'));

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

-- =====================================================================
-- PHASE B (0022b): rewrite the data + tighten the CHECK. RUN AFTER the new api is live.
-- =====================================================================

update public.scenario_matrix set tier = 'Adapted' where tier = 'Modified';
update public.activity_record set tier = 'Adapted' where tier = 'Modified';
update public.pulse_record set tier_recommended = 'Adapted' where tier_recommended = 'Modified';

alter table public.scenario_matrix drop constraint if exists scenario_matrix_tier_check;
alter table public.scenario_matrix
    add constraint scenario_matrix_tier_check
    check (tier in ('Full', 'Adapted', 'Pivot'));

alter table public.activity_record drop constraint if exists activity_record_tier_check;
alter table public.activity_record
    add constraint activity_record_tier_check
    check (tier in ('Full', 'Adapted', 'Pivot'));

alter table public.pulse_record drop constraint if exists pulse_record_tier_recommended_check;
alter table public.pulse_record
    add constraint pulse_record_tier_recommended_check
    check (tier_recommended in ('Full', 'Adapted', 'Pivot'));
