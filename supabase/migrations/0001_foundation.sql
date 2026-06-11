-- Migration 0001: v3 foundation tables (user_profile, child_profile) + RLS.
--
-- These are the two STABLE v3 foundation tables from Product.md section 5 and
-- HardRules/Api/Modules/Models.md. They are ADDITIVE: they create new v3 tables
-- alongside the prototype's existing tables (profiles, children, chapters,
-- triggers), which are replaced in later tasks. Nothing here drops or alters a
-- prototype table.
--
-- D8 (Docs/Decisions.md): child_profile is modelled as a general CARE RECIPIENT
-- (a person with additional needs across the lifespan, child and adult/elder
-- care), not something hard-fitted to "child". The MVP UI may still say "child";
-- the name is kept for the MVP, but the columns and relationships do not assume
-- a child, so adult care is not a schema rewrite later.
--
-- Schema is owned by these migrations only (no create_all, no live table edits).
-- gen_random_uuid() is a core Postgres function (13+, Supabase runs 15+), so no
-- extension is required.

-- =====================================================================
-- user_profile
-- One row per authenticated user, keyed to Supabase Auth (auth.users).
-- =====================================================================
create table if not exists public.user_profile (
    id                  uuid primary key references auth.users (id) on delete cascade,
    email               text,
    first_name          text not null,
    subscription_tier   text not null default 'free',
    onboarding_complete boolean not null default false,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- =====================================================================
-- child_profile (general care recipient, per D8)
-- One row per care recipient, owned by a user. The MVP models one active
-- recipient per user (multiple recipients are deferred, Product.md section 6).
-- =====================================================================
create table if not exists public.child_profile (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,
    name                text not null,
    age_band            text,
    support_level_code  text check (support_level_code in ('SL-LOW', 'SL-MED', 'SL-HIGH')),
    tags                text[] not null default '{}',
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- Scope queries by owner: every child_profile read filters on user_id.
create index if not exists idx_child_profile_user_id on public.child_profile (user_id);

-- =====================================================================
-- updated_at maintenance
-- A single trigger function shared by both tables keeps updated_at honest at
-- the database layer (a client cannot forget to set it). BEFORE UPDATE so the
-- new row carries the fresh timestamp.
-- =====================================================================
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_user_profile_updated_at on public.user_profile;
create trigger trg_user_profile_updated_at
    before update on public.user_profile
    for each row
    execute function public.set_updated_at();

drop trigger if exists trg_child_profile_updated_at on public.child_profile;
create trigger trg_child_profile_updated_at
    before update on public.child_profile
    for each row
    execute function public.set_updated_at();

-- =====================================================================
-- Row Level Security
-- RLS is the database backstop for multi-tenant isolation (server-side user
-- scoping is the first line). A user reads and writes only their own rows.
-- Policies are explicit per operation (no FOR ALL). drop ... if exists keeps
-- the migration re-runnable.
-- =====================================================================

-- user_profile: a user may read and update only their own row. There is no
-- insert or delete policy here: profile rows are created server-side on sign-up
-- (service role / trigger, a later task) and are removed by the auth.users
-- cascade, not by the user directly.
alter table public.user_profile enable row level security;

drop policy if exists user_profile_select_own on public.user_profile;
create policy user_profile_select_own
    on public.user_profile
    for select
    using (auth.uid() = id);

drop policy if exists user_profile_update_own on public.user_profile;
create policy user_profile_update_own
    on public.user_profile
    for update
    using (auth.uid() = id)
    with check (auth.uid() = id);

-- child_profile: a user may select, insert, update, and delete only rows they
-- own (user_id = auth.uid()). The with check on insert/update prevents a user
-- from writing or moving a row to another owner.
alter table public.child_profile enable row level security;

drop policy if exists child_profile_select_own on public.child_profile;
create policy child_profile_select_own
    on public.child_profile
    for select
    using (auth.uid() = user_id);

drop policy if exists child_profile_insert_own on public.child_profile;
create policy child_profile_insert_own
    on public.child_profile
    for insert
    with check (auth.uid() = user_id);

drop policy if exists child_profile_update_own on public.child_profile;
create policy child_profile_update_own
    on public.child_profile
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists child_profile_delete_own on public.child_profile;
create policy child_profile_delete_own
    on public.child_profile
    for delete
    using (auth.uid() = user_id);
