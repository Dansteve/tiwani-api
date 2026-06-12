-- Migration 0018: the subscription + entitlement foundation (DB-driven gating).
--
-- Backs the Subscription feature (Docs/FeatureDecisions.md, the Subscription DEFER
-- entry: the 6 hard preconditions + the mandatory refinements; HardRules/Api/Modules/
-- Subscription.md). The shape is three tables plus a narrow privileged write path:
--
--   plan_tier            the tiers, their human names, and their PRICES (monthly /
--                        yearly) and Stripe price ids. Prices AND the free/paid split
--                        live in DATA here, owner-configurable with no redeploy.
--   feature_entitlement  the per-tier VALUE of each gateable feature (an ALLOWLIST of
--                        PAID features; the must-stay-free safety net is never listed).
--   subscription         one row per user: their tier, billing status, period end, and
--                        the Stripe ids. Owner-SELECT-only, NO user write policy: the
--                        ONLY writer is the billing webhook via the SECURITY DEFINER RPC.
--   billing_event        the idempotency ledger: one row per processed Stripe event id
--                        (UNIQUE), so a replayed webhook is a no-op (Stripe at-least-once).
--
-- THE WEBHOOK WRITE PATH (precondition 3, the 0007 card-token precedent). A user must
-- NEVER be able to set their own tier (precondition 2: the self-grant fix removed
-- subscription_tier from UserProfileUpdate, and there is no user write policy on these
-- tables). Subscription state is written ONLY by the billing webhook, which authenticates
-- by STRIPE SIGNATURE (not a Supabase session). The webhook calls the narrow SECURITY
-- DEFINER function public.apply_subscription_event below, which runs past RLS to record the
-- event (idempotently) and upsert the subscription. Unlike get_card_by_token (0007), this
-- function is NOT granted to anon/authenticated: it is reached only with the service-role
-- key on the server-side webhook path, so a logged-in user cannot call it to promote
-- themselves.
--
-- PENDING OWNER APPLY: like 0013, this migration is NOT applied to production by this
-- feature change. It lands here under version control; the owner applies it on the direct
-- Postgres path (Docs/Decisions.md D12) when the subscription feature goes live. The seed
-- block at the foot loads the board split as the configurable DEFAULT so a freshly-applied
-- DB is correct out of the box; the owner edits the rows (prices, the split) afterwards
-- with no code change.
--
-- ADDITIVE + IDEMPOTENT: creates four new tables, indexes, RLS policies, and one function;
-- it drops or alters no existing object. Schema is owned by this migration (no create_all,
-- no live table edits). gen_random_uuid() is core Postgres (Supabase 15+); no extension.

-- =====================================================================
-- plan_tier
-- The tiers and their PRICES. GLOBAL reference data (like scenario_matrix): every
-- authenticated user may READ it (the app shows the plan/price list); NO user may write
-- it (only the seed/owner edits the rows, the same write-for-none posture as the seed
-- tables). The KEY is the join key used by feature_entitlement and subscription and by
-- user_profile.subscription_tier; the prices are numeric so money is exact.
-- =====================================================================
create table if not exists public.plan_tier (
    key                       text primary key
                                  check (key in ('free', 'standard', 'premium')),
    name                      text not null,
    -- Monthly / yearly price in GBP pence (integer minor units), so money is exact and
    -- never a float. Null where a tier has no charge (free) or that cadence is not sold.
    price_monthly_pence       integer check (price_monthly_pence is null or price_monthly_pence >= 0),
    price_yearly_pence        integer check (price_yearly_pence  is null or price_yearly_pence  >= 0),
    -- The Stripe Price ids for each cadence. NULL until the owner creates the prices in
    -- Stripe (PENDING OWNER STRIPE KEYS); the checkout path reads them, never hardcodes.
    stripe_price_id_monthly   text,
    stripe_price_id_yearly    text,
    -- Whether the tier is currently offered (an owner can retire a tier without deleting
    -- its historical subscriptions). The checkout path only sells active tiers.
    active                    boolean not null default true,
    -- Display order (free first). A small int so the app lists tiers deterministically.
    sort                      integer not null default 0,
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now()
);

-- =====================================================================
-- feature_entitlement
-- The per-tier VALUE of each gateable feature, the ALLOWLIST the gate reads. One row per
-- (feature_key, tier_key). This table lists ONLY the PAID/convenience features that are
-- gated (e.g. recipients.max, card.pdf_export, themes); the must-stay-free safety-net keys
-- are NEVER listed here and NEVER pass through the gate (the red-line, enforced in code by
-- app/services/entitlements.MUST_STAY_FREE). value is text so a key can hold an int
-- ("2"/"3"/"unlimited"), a bool ("true"/"false"), or a future enum; the gate parses it.
-- GLOBAL reference data: read-for-authenticated, write-for-none (seed/owner only).
-- =====================================================================
create table if not exists public.feature_entitlement (
    feature_key   text not null,
    tier_key      text not null references public.plan_tier (key) on delete cascade,
    value         text not null,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    primary key (feature_key, tier_key)
);

create index if not exists idx_feature_entitlement_feature
    on public.feature_entitlement (feature_key);

-- =====================================================================
-- subscription
-- One row per user: their CURRENT tier, billing status, period end, and Stripe ids.
-- USER-scoped but with a CRUCIAL difference from every other user table: there is a
-- SELECT policy (a user reads their OWN subscription) but NO insert/update/delete policy
-- for the user, so a user can read their tier yet can NEVER write it. The only writer is
-- the billing webhook through public.apply_subscription_event (SECURITY DEFINER, below),
-- which runs as the function owner and is not callable from a user session.
--
-- stripe_event_id holds the id of the LAST Stripe event applied to this row (UNIQUE
-- across the table), one half of the idempotency story; billing_event is the full ledger.
-- =====================================================================
create table if not exists public.subscription (
    user_id                  uuid primary key references auth.users (id) on delete cascade,
    tier_key                 text not null default 'free'
                                 references public.plan_tier (key),
    -- The billing status mirrored from Stripe (Stripe is the source of truth). The set
    -- mirrors Stripe subscription statuses; 'none' is the local default before any billing.
    status                   text not null default 'none'
                                 check (status in (
                                     'none', 'trialing', 'active', 'past_due',
                                     'canceled', 'incomplete', 'incomplete_expired',
                                     'unpaid', 'paused'
                                 )),
    current_period_end       timestamptz,
    stripe_customer_id       text,
    stripe_subscription_id   text,
    -- The last applied Stripe event id (UNIQUE): the webhook will not re-apply an event it
    -- already wrote here. The fuller idempotency guard is billing_event (every event id).
    stripe_event_id          text unique,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now()
);

-- =====================================================================
-- billing_event
-- The webhook idempotency ledger (precondition 4): one row per Stripe event id ever
-- processed, UNIQUE on the id. Stripe delivers AT LEAST ONCE, so the same event can arrive
-- twice; apply_subscription_event inserts here first and treats a duplicate as a no-op, so
-- a replay never double-applies. NOT user data: it is billing-system bookkeeping, so it has
-- NO user-facing policy at all (RLS on, no policy -> a normal user reads/writes nothing;
-- only the SECURITY DEFINER function and the service role touch it).
-- =====================================================================
create table if not exists public.billing_event (
    stripe_event_id   text primary key,
    event_type        text,
    user_id           uuid,
    received_at       timestamptz not null default now()
);

-- =====================================================================
-- updated_at maintenance: reuse the shared trigger function from 0001.
-- =====================================================================
drop trigger if exists trg_plan_tier_updated_at on public.plan_tier;
create trigger trg_plan_tier_updated_at
    before update on public.plan_tier
    for each row
    execute function public.set_updated_at();

drop trigger if exists trg_feature_entitlement_updated_at on public.feature_entitlement;
create trigger trg_feature_entitlement_updated_at
    before update on public.feature_entitlement
    for each row
    execute function public.set_updated_at();

drop trigger if exists trg_subscription_updated_at on public.subscription;
create trigger trg_subscription_updated_at
    before update on public.subscription
    for each row
    execute function public.set_updated_at();

-- =====================================================================
-- Row Level Security
--
-- plan_tier + feature_entitlement: GLOBAL reference data. RLS ON; SELECT granted to the
-- authenticated role (the app reads the price list and the per-tier values), and NO write
-- policy (so no user can edit a price or an entitlement). Same posture as the seed tables
-- in 0002.
--
-- subscription: USER data, READ-ONLY to the user. RLS ON; a SELECT policy lets a user read
-- their OWN row (auth.uid() = user_id), and there is deliberately NO insert/update/delete
-- policy: a user can SEE their tier but can NEVER set it. The only writer is the webhook
-- through the SECURITY DEFINER RPC.
--
-- billing_event: billing bookkeeping. RLS ON; NO policy at all, so a normal authenticated
-- user reads and writes nothing here; only the SECURITY DEFINER function and the service
-- role touch it.
-- =====================================================================
alter table public.plan_tier enable row level security;

drop policy if exists plan_tier_select_authenticated on public.plan_tier;
create policy plan_tier_select_authenticated
    on public.plan_tier
    for select
    to authenticated
    using (true);

alter table public.feature_entitlement enable row level security;

drop policy if exists feature_entitlement_select_authenticated on public.feature_entitlement;
create policy feature_entitlement_select_authenticated
    on public.feature_entitlement
    for select
    to authenticated
    using (true);

alter table public.subscription enable row level security;

-- A user may READ only their own subscription. There is NO insert/update/delete policy for
-- the user on this table: this is the self-grant fix at the database layer. Even if a user
-- somehow forged a write, RLS has no policy permitting it, so it is refused.
drop policy if exists subscription_select_own on public.subscription;
create policy subscription_select_own
    on public.subscription
    for select
    to authenticated
    using (auth.uid() = user_id);

-- RLS on, no policy: a normal user touches nothing in the idempotency ledger.
alter table public.billing_event enable row level security;

-- =====================================================================
-- The webhook write path (no Supabase session): apply_subscription_event(...)
--
-- SECURITY DEFINER so it runs with the function owner's rights and can write past RLS,
-- which is what the billing webhook needs (it authenticates by Stripe signature, not a
-- user session) and what a user must NOT be able to do. It is deliberately NARROW and
-- IDEMPOTENT:
--   - it FIRST records the Stripe event id in billing_event; if that id was already
--     processed (Stripe at-least-once delivery), it returns false WITHOUT touching the
--     subscription, so a replay is a safe no-op.
--   - otherwise it UPSERTS the caller-named user's subscription row to the new tier /
--     status / period / Stripe ids and stamps stripe_event_id, then returns true.
-- It writes ONLY the subscription identified by p_user_id (resolved by the webhook from
-- the Stripe customer/subscription, Stripe being the source of truth); it never reads or
-- returns another user's data.
--
-- search_path is pinned empty and every reference is schema-qualified (the standard
-- SECURITY DEFINER hardening, as in 0007). EXECUTE is granted to NO public role: this
-- function is reached only with the service-role key on the server-side webhook path, so
-- the broad default is revoked and NOT re-granted to anon/authenticated (the opposite of
-- get_card_by_token, which a public share link must reach). The service role bypasses the
-- grant check, so the webhook can still call it.
-- =====================================================================
create or replace function public.apply_subscription_event(
    p_event_id              text,
    p_user_id               uuid,
    p_tier_key              text,
    p_status                text,
    p_current_period_end    timestamptz,
    p_stripe_customer_id    text,
    p_stripe_subscription_id text,
    p_event_type            text default null
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
    -- Idempotency: record the event id first. A duplicate (already-processed) event id
    -- collides on the primary key, so we treat it as a no-op and do NOT re-apply.
    insert into public.billing_event (stripe_event_id, event_type, user_id)
    values (p_event_id, p_event_type, p_user_id)
    on conflict (stripe_event_id) do nothing;

    if not found then
        -- The event id was already in the ledger: a replay. Do not write the subscription.
        return false;
    end if;

    -- Upsert the user's subscription to the state Stripe reported (Stripe is the source of
    -- truth). One row per user (user_id is the PK), so a returning customer updates in place.
    insert into public.subscription (
        user_id, tier_key, status, current_period_end,
        stripe_customer_id, stripe_subscription_id, stripe_event_id
    )
    values (
        p_user_id, p_tier_key, p_status, p_current_period_end,
        p_stripe_customer_id, p_stripe_subscription_id, p_event_id
    )
    on conflict (user_id) do update set
        tier_key               = excluded.tier_key,
        status                 = excluded.status,
        current_period_end     = excluded.current_period_end,
        stripe_customer_id     = excluded.stripe_customer_id,
        stripe_subscription_id = excluded.stripe_subscription_id,
        stripe_event_id        = excluded.stripe_event_id;

    return true;
end;
$$;

-- This function must NOT be callable from a user session (a logged-in user could otherwise
-- promote themselves). Revoke the broad default and grant EXECUTE to NO public role; the
-- webhook reaches it with the service-role key, which bypasses the grant check.
revoke all on function public.apply_subscription_event(
    text, uuid, text, text, timestamptz, text, text, text
) from public;

-- =====================================================================
-- SEED: the board split as the configurable DEFAULT (Docs/FeatureDecisions.md)
--
-- Loaded inline so a freshly-applied database is correct out of the box; the owner edits
-- these rows (prices, the split) afterwards with NO code change (prices + the split live in
-- DATA, the whole point). Idempotent: on conflict do update, so re-applying the migration
-- re-asserts the defaults without erroring.
--
-- Prices: Product.md section 8 names the three monthly tiers (the PRD line "9.99 / 19.99 /
-- 29." with the figure cut off in the markdown; the literal source is "9.99 / 19.99 /
-- 29.99"). Stored as pence: free 0, standard 1999, premium 2999. Yearly is left NULL until
-- the owner sets it (no yearly price is stated in the PRD). Stripe price ids are NULL
-- (PENDING OWNER STRIPE KEYS).
-- =====================================================================
insert into public.plan_tier (key, name, price_monthly_pence, price_yearly_pence, active, sort)
values
    ('free',     'Free',     0,    null, true, 0),
    ('standard', 'Standard', 1999, null, true, 1),
    ('premium',  'Premium',  2999, null, true, 2)
on conflict (key) do update set
    name                = excluded.name,
    price_monthly_pence = excluded.price_monthly_pence,
    active              = excluded.active,
    sort                = excluded.sort;

-- feature_entitlement: the board split. ONLY paid/convenience keys are listed (the gate is
-- an ALLOWLIST of these; the safety net is never here).
--   recipients.max   free=2 / standard=3 / premium=unlimited  (free covers TWO recipients,
--                    the board red-line)
--   card.pdf_export  paid (free=false, standard=true, premium=true)
--   themes           paid (free=false, standard=true, premium=true)
insert into public.feature_entitlement (feature_key, tier_key, value)
values
    ('recipients.max', 'free',     '2'),
    ('recipients.max', 'standard', '3'),
    ('recipients.max', 'premium',  'unlimited'),
    ('card.pdf_export', 'free',     'false'),
    ('card.pdf_export', 'standard', 'true'),
    ('card.pdf_export', 'premium',  'true'),
    ('themes', 'free',     'false'),
    ('themes', 'standard', 'true'),
    ('themes', 'premium',  'true')
on conflict (feature_key, tier_key) do update set
    value = excluded.value;
