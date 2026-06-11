-- Migration 0005: alert_record (the active Erosion Alert per chapter) + RLS.
--
-- One USER-DATA table for the Erosion Alerts (Product.md section 4.9, AUTHORITATIVE;
-- the copy is GOVERNED and gated on psychiatrist sign-off before launch, Task 12),
-- the object in section 5 / HardRules/Api/Modules/Models.md. RLS user-scoped the same
-- way as activity_record / pulse_record / lci_snapshot (migrations 0003 / 0004): a
-- user reads and writes only their own rows. ADDITIVE: a new v3 table; nothing here
-- drops or alters another.
--
-- alert_record holds the CURRENT active alert for a (user, chapter): the level (1/2/3),
-- the trigger condition that fired it, and the dismissed state. It is evaluated after
-- every pulse (app/services/alerts.py): a higher level REPLACES a lower one (section
-- 4.9), so there is at most one active alert per chapter, enforced by the
-- (user_id, chapter) UNIQUE: the post-pulse evaluation UPSERTs the single row.
--
-- Dismissal (section 4.9): the Coordinator can dismiss an alert; a dismissed alert
-- returns only if conditions worsen PAST THE NEXT THRESHOLD. We store `dismissed` plus
-- `dismissed_level` (the level dismissed at), so a dismissed L1 stays hidden until the
-- evaluation computes a strictly HIGHER level (L2/L3), which re-activates the row.
--
-- Schema is owned by this migration only (no create_all, no live table edits).
-- gen_random_uuid() is core Postgres (Supabase runs 15+); no extension needed.

-- =====================================================================
-- alert_record
-- The current active Erosion Alert for a user's chapter (section 4.9).
-- =====================================================================
create table if not exists public.alert_record (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,

    -- The chapter this alert is for. One active alert per (user, chapter): the
    -- post-pulse evaluation UPSERTs this row (a higher level replaces a lower one).
    chapter             text not null check (
                            chapter in ('school', 'career', 'family', 'social', 'travel', 'culture')
                        ),

    -- The active level: 1 Early signal, 2 Sustained pressure, 3 Critical erosion
    -- (section 4.9). A higher level replaces a lower one, so the stored value is the
    -- highest currently met.
    level               smallint not null check (level in (1, 2, 3)),

    -- The section 4.9 condition that fired the active level (a short stable code, for
    -- audit and for the app/QA to see WHY it fired). Free-form text, never read by any
    -- engine; the level above is the structured signal. Examples:
    -- 'l1_counts_30d', 'l2_counts_30d', 'l2_lci_decline_3wk', 'l3_counts_14d',
    -- 'l3_lci_below_30'.
    trigger_condition   text not null,

    -- Dismissal state (section 4.9). dismissed = the Coordinator hid the current
    -- alert; dismissed_level = the level it was dismissed at, so the alert only
    -- returns when the evaluation computes a strictly higher level (worsen past the
    -- next threshold). dismissed_level is null while the alert is active.
    dismissed           boolean not null default false,
    dismissed_level     smallint check (dismissed_level in (1, 2, 3)),

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    -- At most one alert row per (user, chapter): the active-alert invariant and the
    -- UPSERT target for the post-pulse evaluation.
    constraint uq_alert_record_user_chapter unique (user_id, chapter)
);

-- The dashboard and the alerts endpoint read a user's active alerts; scope by owner.
create index if not exists idx_alert_record_user_chapter
    on public.alert_record (user_id, chapter);

-- updated_at maintenance: reuse the shared trigger from migration 0001.
drop trigger if exists trg_alert_record_updated_at on public.alert_record;
create trigger trg_alert_record_updated_at
    before update on public.alert_record
    for each row
    execute function public.set_updated_at();

-- =====================================================================
-- Row Level Security
-- alert_record is user data: a user may select, insert, update, and delete only rows
-- they own (user_id = auth.uid()). The with check on insert/update prevents writing
-- or moving a row to another owner. Same pattern as pulse_record (migration 0004).
-- RLS is the database backstop; the service scopes every query by user_id (the first
-- line).
-- =====================================================================
alter table public.alert_record enable row level security;

drop policy if exists alert_record_select_own on public.alert_record;
create policy alert_record_select_own
    on public.alert_record
    for select
    using (auth.uid() = user_id);

drop policy if exists alert_record_insert_own on public.alert_record;
create policy alert_record_insert_own
    on public.alert_record
    for insert
    with check (auth.uid() = user_id);

drop policy if exists alert_record_update_own on public.alert_record;
create policy alert_record_update_own
    on public.alert_record
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists alert_record_delete_own on public.alert_record;
create policy alert_record_delete_own
    on public.alert_record
    for delete
    using (auth.uid() = user_id);
