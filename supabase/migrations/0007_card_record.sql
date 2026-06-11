-- Migration 0007: card_record (the shareable Continuity Card) + RLS + a careful
-- token read path.
--
-- The Continuity Card (Product.md section 4.6, HardRules/Api/Modules/Cards.md) is a
-- one-page support summary a Coordinator generates for a HELPER (a babysitter,
-- teacher, or respite carer) who looks after the care recipient for one activity.
-- It restates that activity's plan in plain, warm, NON-CLINICAL words. It is shared
-- via a link that needs NO account: the helper just opens the link.
--
-- card_record is USER DATA: it is owned by a user and tied to their care recipient
-- and the activity_record it was generated from. RLS is user-scoped the same way as
-- activity_record / alert_record (migrations 0003 / 0005): the owner
-- (auth.uid() = user_id) may CRUD only their own rows. ADDITIVE: a new v3 table;
-- nothing here drops or alters another.
--
-- THE TOKEN READ IS A SEPARATE, CAREFUL PATH. The share link carries one secret: an
-- opaque token. A token holder is NOT authenticated, so RLS (keyed to auth.uid())
-- correctly returns them ZERO rows on a direct select. The only way to read a card
-- without auth is the SECURITY DEFINER function public.get_card_by_token below, which
-- takes the token, and ONLY when the card exists and has not expired returns ONLY the
-- safe content jsonb, never user_id / child_id / activity_id / the token itself. The
-- content was already assembled to be safe (the care recipient's FIRST name only, no
-- clinical data); the function is the second line that makes it physically impossible
-- to reach any other column or any other row with a token.
--
-- Schema is owned by this migration only (no create_all, no live table edits).
-- gen_random_uuid() is core Postgres (Supabase runs 15+); no extension needed.

-- =====================================================================
-- card_record
-- One generated Continuity Card for a user's activity_record (section 4.6).
-- =====================================================================
create table if not exists public.card_record (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,
    child_id            uuid not null references public.child_profile (id) on delete cascade,
    activity_id         uuid not null references public.activity_record (id) on delete cascade,

    -- The opaque share token: the ONLY secret in the link. Generated with a
    -- cryptographically strong source (secrets.token_urlsafe) in the service, so it
    -- is hard to guess. UNIQUE so a token resolves to at most one card; the token
    -- read path (the function below) looks a card up by this column.
    token               text not null unique,

    -- The assembled, ALREADY-SAFE card content (the section 4.6 one-pager) as jsonb:
    -- the care recipient's first name only, the activity name, the participation tier
    -- in plain words, a short supportive intro, the top strategies, and an "if things
    -- get difficult" line. NO special-category health data, NO clinical language, NO
    -- PII beyond the first name (the builder enforces this and runs the copy through
    -- the shared non-clinical guard). This is the only thing the token read returns.
    content             jsonb not null,

    -- The link is valid 30 DAYS (section 4.6 / Product.md section 3.3). Set by the
    -- service to created_at + 30 days. The token read returns the card ONLY while
    -- now() < expires_at; an expired link reads as not found (the app shows a friendly
    -- "ask the family for a new one" page).
    expires_at          timestamptz not null,

    created_at          timestamptz not null default now()
);

-- The owner lists/reads their own cards; the token path looks up by token. Index
-- both access patterns.
create index if not exists idx_card_record_user
    on public.card_record (user_id);

create index if not exists idx_card_record_token
    on public.card_record (token);

-- =====================================================================
-- Row Level Security
-- card_record is user data: the OWNER (auth.uid() = user_id) may select, insert,
-- update, and delete only their own rows. The with check on insert/update prevents
-- writing or moving a row to another owner. Same pattern as activity_record
-- (migration 0003) and alert_record (migration 0005). RLS is the database backstop;
-- the service also scopes every owner query by user_id (the first line).
--
-- A token holder is NOT authenticated (auth.uid() is null), so these policies return
-- them NOTHING on a direct select: the token read goes ONLY through the SECURITY
-- DEFINER function below, never through a table select.
-- =====================================================================
alter table public.card_record enable row level security;

drop policy if exists card_record_select_own on public.card_record;
create policy card_record_select_own
    on public.card_record
    for select
    using (auth.uid() = user_id);

drop policy if exists card_record_insert_own on public.card_record;
create policy card_record_insert_own
    on public.card_record
    for insert
    with check (auth.uid() = user_id);

drop policy if exists card_record_update_own on public.card_record;
create policy card_record_update_own
    on public.card_record
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists card_record_delete_own on public.card_record;
create policy card_record_delete_own
    on public.card_record
    for delete
    using (auth.uid() = user_id);

-- =====================================================================
-- The token read path (no auth): get_card_by_token(token) -> content
--
-- SECURITY DEFINER so it runs with the function owner's rights and can read the row
-- past RLS, which is exactly what an unauthenticated token holder needs and cannot do
-- with a direct select. It is deliberately NARROW:
--   - it takes only the token (the link's single secret),
--   - it returns ONLY the content jsonb (never user_id / child_id / activity_id /
--     token / timestamps), so no owner identifier or foreign key can leak,
--   - it returns a row ONLY when the card exists AND has not expired
--     (expires_at > now()); an expired or unknown token returns zero rows, which the
--     route maps to 404.
-- The content itself was assembled safe (first name only, no clinical data); this
-- function guarantees a token can reach nothing more than that one card's safe copy.
--
-- search_path is pinned to empty + the schema is fully qualified, the standard
-- hardening for a SECURITY DEFINER function (so the owner's path cannot be hijacked).
-- EXECUTE is granted to anon (and authenticated) because the share link is used
-- without a session; the function's own narrowness is the boundary, not the caller.
-- =====================================================================
create or replace function public.get_card_by_token(p_token text)
returns jsonb
language sql
security definer
set search_path = ''
stable
as $$
    select c.content
    from public.card_record c
    where c.token = p_token
      and c.expires_at > now();
$$;

-- The token read is reachable without a session (the helper has no account). The
-- function returns only the safe content and only for a live token; revoke the broad
-- default and grant EXECUTE explicitly to the anon and authenticated roles.
revoke all on function public.get_card_by_token(text) from public;
grant execute on function public.get_card_by_token(text) to anon;
grant execute on function public.get_card_by_token(text) to authenticated;
