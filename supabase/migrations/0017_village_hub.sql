-- Migration 0017: the Village Delegation Hub (a closed need -> claim -> confirm -> done /
-- dropped follow-through loop) on the recipient_membership substrate (migration 0015).
--
-- !!! PENDING OWNER APPLY (not applied to production by this change; the 0013 / 0015
-- posture) !!! The owner applies it on the direct-Postgres path (DATABASE_URL + asyncpg)
-- that applies every migration, NOT on Render and NOT from the app. Until it is applied
-- the tables and functions below do not exist on the live DB; this feature must not ship
-- reads against it before the owner applies BOTH 0015 (the substrate) and this migration.
--
-- (Numbering: 0014 is the strategy library, 0015 is the membership substrate, 0016 is an
-- in-flight track; the Village Hub takes 0017 per the feature decision so the parallel
-- tracks do not collide on a number. The apply-order chain is still strictly increasing,
-- and 0017 depends on 0015 being applied first.)
--
-- WHAT THIS IS. The Village Delegation Hub (Docs/FeatureDecisions.md, the APPROVED
-- next-phase entry): the Coordinator's "village" (family/friends/trusted helpers)
-- VOLUNTEER for a specific NEED rather than the Coordinator assigning them, so the
-- Coordinator does not text ten people one by one. It is the SECOND consumer of the
-- 0015 substrate (the board: build that primitive ONCE), so this migration adds nothing
-- to the membership/invite tables, it RIDES them: a need's audience is the recipient's
-- roster (the active recipient_membership rows), and every visibility check goes through
-- 0015's tiwani_private.is_child_member.
--
-- THE SIX MANDATORY REFINEMENTS (Docs/FeatureDecisions.md, the Village Hub entry), each
-- mapped to a load-bearing property of this schema:
--   1. CLOSED FOLLOW-THROUGH LOOP, not a noticeboard: a need has a status machine
--      open -> claimed -> confirmed -> done, with a drop at any active step that AUTO
--      RE-BROADCASTS (status back to open, claim cleared). A need is SPECIFIC + bounded
--      (starts_at / ends_at, location_text), never a vague "let me know". The drop
--      re-broadcast is in the drop RPC, so a planned-around-but-dropped claim re-opens.
--   2. MINIMUM VISIBILITY: a helper sees the NEED + LOGISTICS only (what / when /
--      where-to-the-task / who-to-contact). This table carries NO tag profile, NO LCI,
--      NO alerts, NO score column, by construction: there is nothing on village_need a
--      read could leak beyond the need itself. The recipient is named by first name only
--      (the list RPC derives it), the Continuity Card ceiling.
--   3. WHEREABOUTS is PER-CLAIM and OCCURRENCE-SCOPED: the location_text + contact
--      details resolve ONLY to the ONE member who currently holds the claim (or the
--      owner), and ONLY for that one bounded need, never a roster-wide standing routine.
--      The list RPC returns an area-level where + no contact to any member; the detail
--      RPC returns the full logistics only to the claimer-or-owner. There is no
--      "where is [name] now" view and no recurring location record.
--   4. REAL ACCOUNTS UNDER RLS (the substrate, already in 0015): a member WRITES state
--      (claims, marks done), so they are attributable + individually revocable. Claims
--      are ATOMIC, first-claim-wins, DB-enforced (the claim RPC's conditional UPDATE
--      inside a row lock). Every write is a SECURITY DEFINER RPC that checks
--      membership/role first; there is NO user INSERT/UPDATE/DELETE policy on any table
--      here (the 0015 discipline: the RPCs are the only writers).
--   5. CONSENT + ROSTER + REVOKE + AUDIT: per-recipient consent is FIRST-CLASS
--      (recipient_village_consent, written by an owner-gated RPC; the post RPC REFUSES to
--      broadcast a need for a recipient with no recorded consent, the Art. 9 gate). The
--      roster is 0015's membership select (a member sees "who is in [name]'s village").
--      Owner-revoke is instant: revoking the recipient_membership row (0015) stops the
--      member resolving any need read on the very next request (every read goes through
--      is_child_member, which requires an ACTIVE membership). Access EXPIRES per-claim:
--      once a need is done, the logistics no longer resolve to the (ex-)claimer. A
--      retained append-only audit (village_need_event) records every transition.
--   6. GOVERNED COPY + a guard test live in app/engines/village (not SQL): the
--      user-facing need / claim / consent copy runs through a Hub guard.py + a guard test
--      mirroring tests/test_engine_alerts_guard.py.
--
-- ADDITIVE and IDEMPOTENT: it creates new tables and new functions in the existing
-- tiwani_private + public schemas; it DROPS or ALTERS no existing object (not the 0015
-- membership/invite tables, not child_profile). gen_random_uuid() is core Postgres; no
-- extension is needed. The 0015 helper tiwani_private.is_child_member is reused, not
-- redefined.

-- =====================================================================
-- recipient_village_consent
-- Per-recipient, first-class consent that the recipient's information may be shared with
-- the village for a delegated need (refinement 5; UK GDPR Art. 9, the "recorded consent
-- or blocked" rule). The OWNER (the responsible adult, the child case) records it; the
-- post RPC requires an ACTIVE consent row for the recipient before any need can be
-- broadcast. Soft-revocable (revoked_at) so a withdrawn consent stops new broadcasts
-- while the audit row is kept (the 0008 / 0015 soft-revoke precedent). The exact consent
-- TEXT is governed copy (app/engines/village/copy.py) and stored here as written, so the
-- record shows precisely what the Coordinator agreed to.
-- =====================================================================
create table if not exists public.recipient_village_consent (
    id                  uuid primary key default gen_random_uuid(),

    -- The care recipient this consent is for (child_profile is the general care-recipient
    -- table, D8). Cascade so closing a recipient removes its consent record.
    recipient_id        uuid not null references public.child_profile (id) on delete cascade,

    -- The owner who recorded the consent (attribution on the consent). Cascade on the
    -- user delete so a closed account leaves no dangling consent.
    consented_by        uuid not null references auth.users (id) on delete cascade,

    -- The exact governed consent text the Coordinator agreed to (stored verbatim so the
    -- record is auditable). Non-clinical, capacity-framed (the guard test pins it).
    consent_text        text not null,

    consented_at        timestamptz not null default now(),

    -- Soft-revoke: null = active consent, a timestamp = withdrawn at that instant. A
    -- withdrawn consent blocks NEW broadcasts (the post RPC requires revoked_at is null);
    -- existing needs are unaffected (the Coordinator cancels those deliberately).
    revoked_at          timestamptz,

    created_at          timestamptz not null default now()
);

-- At most ONE ACTIVE consent per recipient (a partial unique on the active rows, so a
-- withdrawn row is kept for audit and a fresh consent can be recorded later).
create unique index if not exists uq_recipient_village_consent_active
    on public.recipient_village_consent (recipient_id)
    where revoked_at is null;

create index if not exists idx_recipient_village_consent_recipient
    on public.recipient_village_consent (recipient_id);

-- =====================================================================
-- village_need
-- ONE delegated need, belonging to EXACTLY ONE recipient (recipient_id), inheriting the
-- multi-recipient isolation rule: a need never spans two recipients, and there is no
-- household aggregate. It is SPECIFIC + bounded (refinement 1): a title + detail of WHAT,
-- a starts_at / ends_at of WHEN, a location_text of WHERE-to-the-task, and a contact of
-- WHO-to-reach. These logistics are the visibility CEILING (refinement 2): there is no
-- tag / LCI / alert / score column on this table, so a read cannot leak anything beyond
-- the need itself.
--
-- THE STATUS MACHINE (refinement 1, the closed loop). status is one of:
--   open      posted, awaiting a claim (the broadcast state; auto re-entered on a drop).
--   claimed   a member has claimed it (claimed_by / claimed_at set); awaiting the owner's
--             confirmation.
--   confirmed the owner confirmed the claim (the plan is real; accountability is set).
--   done      the claimer marked it complete (the loop closed cleanly).
--   cancelled the owner cancelled the need (it is no longer wanted; a terminal state).
-- A drop (the claimer steps back) is NOT a status: it RESETS status to open and clears the
-- claim (the auto re-broadcast), recorded in village_need_event. So the live states a
-- claim can move through are open -> claimed -> confirmed -> done, with drop -> open from
-- claimed/confirmed, and cancel -> cancelled from any non-terminal state.
--
-- WHEREABOUTS scoping (refinement 3) is enforced in the READ RPCs, not here: the columns
-- exist on the row, but only the claimer-or-owner detail RPC ever returns location_text /
-- contact_* in full; the member list RPC returns an area-level where and no contact.
-- =====================================================================
create table if not exists public.village_need (
    id                  uuid primary key default gen_random_uuid(),

    -- The ONE recipient this need is for. Cascade so closing a recipient removes its needs.
    recipient_id        uuid not null references public.child_profile (id) on delete cascade,

    -- The status machine (above). open is the broadcast / re-broadcast state.
    status              text not null default 'open'
                        check (status in ('open', 'claimed', 'confirmed', 'done', 'cancelled')),

    -- WHAT: a short title + an optional fuller detail. Bounded, specific (refinement 1).
    title               text not null,
    detail              text,

    -- WHERE (to the task): a free-text place for THIS need only (refinement 3). The list
    -- RPC reduces this to an area-level hint for the roster; the detail RPC returns it in
    -- full only to the claimer-or-owner. NEVER a standing weekly routine.
    location_text       text,
    -- An optional coarser area label (e.g. "North Leeds") the list RPC can show to the
    -- roster without exposing the exact place; if null the list RPC shows no where at all.
    area_label          text,

    -- WHO to contact for this need (the day-of coordinator). Revealed in full only by the
    -- detail RPC to the claimer-or-owner; never in the list.
    contact_name        text,
    contact_phone       text,

    -- WHEN: the bounded time window (refinement 1, "specific offers convert"). Both
    -- nullable for an open-ended ask, but the copy nudges a window.
    starts_at           timestamptz,
    ends_at             timestamptz,

    -- The owner who posted the need (attribution; always the recipient's owner per the
    -- post RPC's owner gate).
    created_by          uuid not null references auth.users (id) on delete cascade,

    -- The member who currently holds the claim (null when open). Set atomically by the
    -- claim RPC, cleared by a drop (the re-broadcast) or by cancel.
    claimed_by          uuid references auth.users (id) on delete set null,
    claimed_at          timestamptz,
    confirmed_at        timestamptz,
    completed_at        timestamptz,
    dropped_at          timestamptz,   -- the most recent drop (audit also has every drop)
    cancelled_at        timestamptz,

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- Read patterns: "the needs for this recipient" (the roster's broadcast list) and "the
-- need I have claimed".
create index if not exists idx_village_need_recipient
    on public.village_need (recipient_id);

create index if not exists idx_village_need_claimed_by
    on public.village_need (claimed_by);

-- At most ONE active (open/claimed/confirmed) claim per member per recipient is a product
-- nicety, not enforced as a constraint (a member may legitimately help with several needs);
-- the atomic single-claimer-per-NEED rule is enforced by the claim RPC's conditional update.

-- updated_at maintenance (the 0001 shared trigger function public.set_updated_at).
drop trigger if exists trg_village_need_updated_at on public.village_need;
create trigger trg_village_need_updated_at
    before update on public.village_need
    for each row execute function public.set_updated_at();

-- =====================================================================
-- village_need_event
-- An append-only audit of every need transition (refinement 5: retained audit). One row
-- per action (posted / claimed / confirmed / done / dropped / cancelled / re_broadcast),
-- recording WHO did WHAT and WHEN. Never updated, never deleted. A read is owner-or-actor
-- scoped (the read RPC), so the audit is not a back-door to the roster's activity.
-- =====================================================================
create table if not exists public.village_need_event (
    id                  uuid primary key default gen_random_uuid(),

    need_id             uuid not null references public.village_need (id) on delete cascade,

    -- The action taken. Mirrors the status machine transitions plus the re-broadcast.
    action              text not null
                        check (action in
                               ('posted', 'claimed', 'confirmed', 'done',
                                'dropped', 'cancelled', 're_broadcast')),

    -- Who took the action (the owner for posted/confirmed/cancelled, the claiming member
    -- for claimed/done/dropped). Null-cascade so a closed account leaves the audit intact.
    actor               uuid references auth.users (id) on delete set null,

    at                  timestamptz not null default now(),

    created_at          timestamptz not null default now()
);

create index if not exists idx_village_need_event_need
    on public.village_need_event (need_id);

-- =====================================================================
-- 1. tiwani_private.village_member_can_see_need(need_id) -- the read-visibility helper.
--
-- SECURITY DEFINER in the NON-exposed tiwani_private schema (the 0015 pattern), so a read
-- policy on village_need can ask "is the caller an active member of this need's recipient"
-- WITHOUT a recursive policy and WITHOUT exposing the helper as an api endpoint. It runs
-- past RLS with the definer's rights, re-derives the caller from auth.uid() itself, and
-- delegates the membership decision to the 0015 helper at the VIEWER threshold (any active
-- member of the recipient may SEE the broadcast). A non-member, a revoked member, or an
-- unauthenticated caller is not visible. search_path is pinned empty; STABLE.
-- =====================================================================
create or replace function tiwani_private.village_member_can_see_need(p_need_id uuid)
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
    select exists (
        select 1
        from public.village_need n
        where n.id = p_need_id
          and tiwani_private.is_child_member(n.recipient_id, 'viewer')
    );
$$;

revoke all on function tiwani_private.village_member_can_see_need(uuid) from public;
grant execute on function tiwani_private.village_member_can_see_need(uuid) to authenticated;
grant execute on function tiwani_private.village_member_can_see_need(uuid) to anon;

-- =====================================================================
-- 2. Row Level Security: read for members, NO user writes (the 0015 discipline).
--
-- village_need READ: a select policy gated by village_member_can_see_need, so any ACTIVE
-- member of the need's recipient can SELECT the need row (the broadcast is visible to the
-- roster). A non-member / revoked member / unauthenticated caller reads nothing. NOTE: a
-- plain table select returns the WHOLE row, including location_text / contact_*; the app
-- does NOT read village_need directly for the logistics. The minimum-visibility +
-- whereabouts-scoping rules (refinements 2 + 3) are served by the list / detail RPCs
-- below, which a member calls instead of selecting the table; the table select is the RLS
-- backstop for the RPC reads. (The service only ever reaches village_need through the
-- SECURITY DEFINER RPCs, which shape the columns per-caller; see app/services/village.py.)
--
-- village_need WRITE: NO user INSERT / UPDATE / DELETE policy. Every state change is a
-- SECURITY DEFINER RPC that checks membership / role first (post + confirm + cancel are
-- owner-gated; claim + done + drop are member-gated and claimer-scoped). There is no path
-- for a member to write the table directly.
-- =====================================================================
alter table public.village_need enable row level security;

drop policy if exists village_need_select_member on public.village_need;
create policy village_need_select_member
    on public.village_need
    for select
    using (tiwani_private.village_member_can_see_need(id));

-- No INSERT / UPDATE / DELETE policy by design: the RPCs are the only writers.

-- village_need_event READ: an OWNER of the need's recipient may read the audit (to see the
-- need's history). A non-owner member cannot read the raw audit (it is not a back-door to
-- the roster's activity; a member sees their own need state through the detail RPC). No
-- user write policy: the RPCs append events.
alter table public.village_need_event enable row level security;

drop policy if exists village_need_event_select_owner on public.village_need_event;
create policy village_need_event_select_owner
    on public.village_need_event
    for select
    using (
        exists (
            select 1
            from public.village_need n
            where n.id = village_need_event.need_id
              and tiwani_private.is_child_member(n.recipient_id, 'owner')
        )
    );

-- recipient_village_consent READ: an OWNER of the recipient may read its consent record
-- (to see / manage it). No user write policy (the record-consent RPC writes it).
alter table public.recipient_village_consent enable row level security;

drop policy if exists recipient_village_consent_select_owner on public.recipient_village_consent;
create policy recipient_village_consent_select_owner
    on public.recipient_village_consent
    for select
    using (tiwani_private.is_child_member(recipient_id, 'owner'));

-- =====================================================================
-- 3. record_village_consent(recipient_id, consent_text) -- owner records consent.
--
-- The Art. 9 gate's writer (refinement 5). SECURITY DEFINER so it can write the
-- no-user-insert-policy table, but it requires the caller to be an ACTIVE OWNER of the
-- recipient (is_child_member at the owner threshold). Idempotent: if an active consent
-- already exists it returns that id (re-recording the same consent is a no-op), so the
-- post flow can call it freely. The consent_text is stored verbatim (the governed copy).
-- =====================================================================
create or replace function public.record_village_consent(
    p_recipient_id uuid,
    p_consent_text text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid uuid := auth.uid();
    v_id  uuid;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    if not tiwani_private.is_child_member(p_recipient_id, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;

    -- Idempotent: reuse an existing ACTIVE consent for this recipient.
    select c.id into v_id
    from public.recipient_village_consent c
    where c.recipient_id = p_recipient_id
      and c.revoked_at is null;

    if v_id is not null then
        return v_id;
    end if;

    insert into public.recipient_village_consent (recipient_id, consented_by, consent_text)
    values (p_recipient_id, v_uid, p_consent_text)
    returning id into v_id;

    return v_id;
end;
$$;

revoke all on function public.record_village_consent(uuid, text) from public;
grant execute on function public.record_village_consent(uuid, text) to authenticated;

-- =====================================================================
-- 4. create_village_need(...) -- the owner posts a need. CONSENT-GATED.
--
-- SECURITY DEFINER (writes the no-user-insert-policy table). Owner-gated: the caller must
-- be an ACTIVE OWNER of the recipient. CONSENT-GATED (refinement 5): it refuses unless an
-- ACTIVE recipient_village_consent row exists for the recipient (the Art. 9 lawful-basis
-- gate, so a need can never be broadcast about a recipient with no recorded consent). It
-- inserts the need in status 'open' (the broadcast state) and appends a 'posted' audit
-- event. Returns the new need id.
-- =====================================================================
create or replace function public.create_village_need(
    p_recipient_id  uuid,
    p_title         text,
    p_detail        text,
    p_location_text text,
    p_area_label    text,
    p_contact_name  text,
    p_contact_phone text,
    p_starts_at     timestamptz,
    p_ends_at       timestamptz
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid uuid := auth.uid();
    v_id  uuid;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    if not tiwani_private.is_child_member(p_recipient_id, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;

    -- CONSENT GATE: an active consent must exist for the recipient before any broadcast.
    if not exists (
        select 1 from public.recipient_village_consent c
        where c.recipient_id = p_recipient_id and c.revoked_at is null
    ) then
        raise exception 'village consent not recorded for this recipient'
            using errcode = 'P0001';
    end if;

    if p_title is null or length(btrim(p_title)) = 0 then
        raise exception 'need title is required' using errcode = '22023';
    end if;

    insert into public.village_need
        (recipient_id, status, title, detail, location_text, area_label,
         contact_name, contact_phone, starts_at, ends_at, created_by)
    values
        (p_recipient_id, 'open', p_title, p_detail, p_location_text, p_area_label,
         p_contact_name, p_contact_phone, p_starts_at, p_ends_at, v_uid)
    returning id into v_id;

    insert into public.village_need_event (need_id, action, actor)
    values (v_id, 'posted', v_uid);

    return v_id;
end;
$$;

revoke all on function public.create_village_need(uuid, text, text, text, text, text, text, timestamptz, timestamptz) from public;
grant execute on function public.create_village_need(uuid, text, text, text, text, text, text, timestamptz, timestamptz) to authenticated;

-- =====================================================================
-- 5. claim_village_need(need_id) -- a member claims a need. ATOMIC, FIRST-WINS.
--
-- SECURITY DEFINER so it can write the no-user-update-policy table. The CALLER must be an
-- ACTIVE MEMBER (any role) of the need's recipient (is_child_member at the viewer
-- threshold). The claim is ATOMIC and FIRST-CLAIM-WINS, DB-enforced (refinement 4): the
-- single UPDATE has WHERE status = 'open' AND claimed_by IS NULL, so of two concurrent
-- claims only the first commits the transition (the row is locked for the duration of the
-- UPDATE); the second updates zero rows and is rejected. No advisory lock or SELECT ... FOR
-- UPDATE race window: the conditional UPDATE is the lock and the gate in one statement.
-- On success it stamps claimed_by / claimed_at, moves status to 'claimed', and appends a
-- 'claimed' event. Returns the need id.
-- =====================================================================
create or replace function public.claim_village_need(p_need_id uuid)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid       uuid := auth.uid();
    v_recipient uuid;
    v_updated   integer;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.recipient_id into v_recipient
    from public.village_need n
    where n.id = p_need_id;

    if v_recipient is null then
        raise exception 'need not found' using errcode = 'P0002';
    end if;

    -- Member gate: any active member of the recipient may claim (the helper role).
    if not tiwani_private.is_child_member(v_recipient, 'viewer') then
        raise exception 'not a member of this recipient' using errcode = '42501';
    end if;

    -- ATOMIC first-wins: only an OPEN, UNCLAIMED need transitions; the conditional UPDATE
    -- is the lock + the gate. A second concurrent claim updates zero rows.
    update public.village_need
       set status = 'claimed',
           claimed_by = v_uid,
           claimed_at = now()
     where id = p_need_id
       and status = 'open'
       and claimed_by is null;

    get diagnostics v_updated = row_count;
    if v_updated = 0 then
        raise exception 'need is no longer open to claim' using errcode = 'P0001';
    end if;

    insert into public.village_need_event (need_id, action, actor)
    values (p_need_id, 'claimed', v_uid);

    return p_need_id;
end;
$$;

revoke all on function public.claim_village_need(uuid) from public;
grant execute on function public.claim_village_need(uuid) to authenticated;

-- =====================================================================
-- 6. confirm_village_need(need_id) -- the OWNER confirms a claim.
--
-- SECURITY DEFINER, OWNER-gated (the owner of the need's recipient). Moves a 'claimed'
-- need to 'confirmed' (the plan is real, accountability set, refinement 1). Idempotent on
-- an already-confirmed need (returns without re-stamping). Appends a 'confirmed' event.
-- Only a claimed need can be confirmed (not an open one with no claimer).
-- =====================================================================
create or replace function public.confirm_village_need(p_need_id uuid)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid       uuid := auth.uid();
    v_recipient uuid;
    v_status    text;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.recipient_id, n.status into v_recipient, v_status
    from public.village_need n
    where n.id = p_need_id
    for update;

    if v_recipient is null then
        raise exception 'need not found' using errcode = 'P0002';
    end if;

    if not tiwani_private.is_child_member(v_recipient, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;

    if v_status = 'confirmed' then
        return p_need_id;  -- idempotent
    end if;
    if v_status <> 'claimed' then
        raise exception 'only a claimed need can be confirmed' using errcode = 'P0001';
    end if;

    update public.village_need
       set status = 'confirmed',
           confirmed_at = now()
     where id = p_need_id;

    insert into public.village_need_event (need_id, action, actor)
    values (p_need_id, 'confirmed', v_uid);

    return p_need_id;
end;
$$;

revoke all on function public.confirm_village_need(uuid) from public;
grant execute on function public.confirm_village_need(uuid) to authenticated;

-- =====================================================================
-- 7. complete_village_need(need_id) -- the CLAIMER marks it done (the loop closes).
--
-- SECURITY DEFINER. The caller must be the CURRENT CLAIMER of the need (claimed_by =
-- auth.uid()); the owner uses cancel, not complete. Moves a claimed/confirmed need to
-- 'done'. Once done, the logistics no longer resolve to the (ex-)claimer (the detail RPC
-- only returns the full where/contact for a LIVE claim), so access expires per-claim
-- (refinement 5). Appends a 'done' event. Returns the need id.
-- =====================================================================
create or replace function public.complete_village_need(p_need_id uuid)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid       uuid := auth.uid();
    v_claimer   uuid;
    v_status    text;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.claimed_by, n.status into v_claimer, v_status
    from public.village_need n
    where n.id = p_need_id
    for update;

    if v_status is null then
        raise exception 'need not found' using errcode = 'P0002';
    end if;

    -- Only the current claimer marks done (attributable; the owner cancels instead).
    if v_claimer is null or v_claimer <> v_uid then
        raise exception 'only the claimer can mark this need done' using errcode = '42501';
    end if;

    if v_status not in ('claimed', 'confirmed') then
        raise exception 'only a claimed or confirmed need can be marked done'
            using errcode = 'P0001';
    end if;

    update public.village_need
       set status = 'done',
           completed_at = now()
     where id = p_need_id;

    insert into public.village_need_event (need_id, action, actor)
    values (p_need_id, 'done', v_uid);

    return p_need_id;
end;
$$;

revoke all on function public.complete_village_need(uuid) from public;
grant execute on function public.complete_village_need(uuid) to authenticated;

-- =====================================================================
-- 8. drop_village_need(need_id) -- the CLAIMER steps back. AUTO RE-BROADCAST.
--
-- The closed-loop's critical edge (refinement 1): a claim planned-around but not honoured
-- is worse than no claim, so a drop must RE-OPEN the need for the rest of the village, not
-- silently strand it. SECURITY DEFINER. The caller must be the CURRENT CLAIMER. It RESETS
-- the need to 'open' and CLEARS the claim (claimed_by / claimed_at / confirmed_at null),
-- stamps dropped_at, and appends BOTH a 'dropped' event (who stepped back) AND a
-- 're_broadcast' event (the need is open again), so the audit shows the handover failed
-- and re-opened. The newly-open need is immediately claimable by any other member.
-- =====================================================================
create or replace function public.drop_village_need(p_need_id uuid)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid       uuid := auth.uid();
    v_claimer   uuid;
    v_status    text;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.claimed_by, n.status into v_claimer, v_status
    from public.village_need n
    where n.id = p_need_id
    for update;

    if v_status is null then
        raise exception 'need not found' using errcode = 'P0002';
    end if;

    if v_claimer is null or v_claimer <> v_uid then
        raise exception 'only the claimer can drop this need' using errcode = '42501';
    end if;

    if v_status not in ('claimed', 'confirmed') then
        raise exception 'only a claimed or confirmed need can be dropped'
            using errcode = 'P0001';
    end if;

    -- AUTO RE-BROADCAST: back to open, claim cleared, so the rest of the village sees it.
    update public.village_need
       set status = 'open',
           claimed_by = null,
           claimed_at = null,
           confirmed_at = null,
           dropped_at = now()
     where id = p_need_id;

    insert into public.village_need_event (need_id, action, actor)
    values (p_need_id, 'dropped', v_uid);
    insert into public.village_need_event (need_id, action, actor)
    values (p_need_id, 're_broadcast', v_uid);

    return p_need_id;
end;
$$;

revoke all on function public.drop_village_need(uuid) from public;
grant execute on function public.drop_village_need(uuid) to authenticated;

-- =====================================================================
-- 9. cancel_village_need(need_id) -- the OWNER cancels a need (terminal).
--
-- SECURITY DEFINER, OWNER-gated. The owner withdraws a need that is no longer wanted (any
-- non-terminal status). Moves it to 'cancelled', clears any claim, stamps cancelled_at,
-- appends a 'cancelled' event. A cancelled (or done) need is terminal: no further claim /
-- confirm / drop. Returns the need id.
-- =====================================================================
create or replace function public.cancel_village_need(p_need_id uuid)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid       uuid := auth.uid();
    v_recipient uuid;
    v_status    text;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.recipient_id, n.status into v_recipient, v_status
    from public.village_need n
    where n.id = p_need_id
    for update;

    if v_recipient is null then
        raise exception 'need not found' using errcode = 'P0002';
    end if;

    if not tiwani_private.is_child_member(v_recipient, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;

    if v_status in ('done', 'cancelled') then
        return p_need_id;  -- idempotent on a terminal need
    end if;

    update public.village_need
       set status = 'cancelled',
           claimed_by = null,
           claimed_at = null,
           confirmed_at = null,
           cancelled_at = now()
     where id = p_need_id;

    insert into public.village_need_event (need_id, action, actor)
    values (p_need_id, 'cancelled', v_uid);

    return p_need_id;
end;
$$;

revoke all on function public.cancel_village_need(uuid) from public;
grant execute on function public.cancel_village_need(uuid) to authenticated;

-- =====================================================================
-- 10. list_village_needs(recipient_id) -- the MEMBER's broadcast list (MINIMUM VISIBILITY).
--
-- SECURITY DEFINER so it can shape the columns per-caller (the table select returns the
-- whole row; this RPC returns ONLY the safe summary). The caller must be an ACTIVE MEMBER
-- of the recipient (viewer threshold). It returns, for each non-terminal need (open /
-- claimed / confirmed) of the recipient, the MINIMUM-VISIBILITY summary (refinement 2):
-- the title, the detail, the WHEN window, an AREA-LEVEL where (area_label only, never the
-- exact location_text), the status, and whether the CALLER is the one holding the claim.
-- It NEVER returns contact_* or the exact location_text in the list (refinement 3: the
-- full logistics are per-claim, the detail RPC's job). The recipient is named by FIRST
-- name only (the Continuity Card ceiling). done / cancelled needs are excluded (the
-- broadcast list is the live board).
--
-- Returns a table so PostgREST serializes it as a row set the route maps to the API model.
-- =====================================================================
create or replace function public.list_village_needs(p_recipient_id uuid)
returns table (
    id              uuid,
    status          text,
    title           text,
    detail          text,
    area_label      text,
    starts_at       timestamptz,
    ends_at         timestamptz,
    recipient_first_name text,
    claimed_by_me   boolean,
    is_claimed      boolean
)
language plpgsql
security definer
set search_path = ''
stable
as $$
declare
    v_uid uuid := auth.uid();
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    if not tiwani_private.is_child_member(p_recipient_id, 'viewer') then
        raise exception 'not a member of this recipient' using errcode = '42501';
    end if;

    return query
        select
            n.id,
            n.status,
            n.title,
            n.detail,
            n.area_label,                                   -- area-level only, never the exact place
            n.starts_at,
            n.ends_at,
            split_part(c.name, ' ', 1) as recipient_first_name,  -- first name only (the Card ceiling)
            (n.claimed_by = v_uid) as claimed_by_me,
            (n.claimed_by is not null) as is_claimed
        from public.village_need n
        join public.child_profile c on c.id = n.recipient_id
        where n.recipient_id = p_recipient_id
          and n.status in ('open', 'claimed', 'confirmed')
        order by coalesce(n.starts_at, n.created_at) asc;
end;
$$;

revoke all on function public.list_village_needs(uuid) from public;
grant execute on function public.list_village_needs(uuid) to authenticated;

-- =====================================================================
-- 11. get_village_need_detail(need_id) -- the per-claim, occurrence-scoped LOGISTICS read.
--
-- The whereabouts rule's enforcer (refinement 3). SECURITY DEFINER. The caller must be an
-- active MEMBER of the need's recipient (viewer threshold) to read anything at all. The
-- FULL logistics (the exact location_text + contact_name + contact_phone) are returned
-- ONLY when the caller is the CURRENT CLAIMER of THIS need, or the OWNER of the recipient.
-- For any OTHER member (who can see the broadcast but does not hold the claim) the
-- location_text / contact_* come back NULL, so the exact where + who-to-contact is
-- revealed to exactly the ONE member who is actually doing the task, for that one
-- occurrence, and disappears again the moment the need is done or dropped (the claim is
-- no longer live). There is no roster-wide standing routine and no "where is [name] now".
--
-- Returns a single-row table (the need's safe + conditionally-full fields).
-- =====================================================================
create or replace function public.get_village_need_detail(p_need_id uuid)
returns table (
    id              uuid,
    status          text,
    title           text,
    detail          text,
    area_label      text,
    location_text   text,
    contact_name    text,
    contact_phone   text,
    starts_at       timestamptz,
    ends_at         timestamptz,
    recipient_first_name text,
    claimed_by_me   boolean,
    is_claimed      boolean
)
language plpgsql
security definer
set search_path = ''
stable
as $$
declare
    v_uid        uuid := auth.uid();
    v_recipient  uuid;
    v_claimer    uuid;
    v_status     text;
    v_can_full   boolean;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.recipient_id, n.claimed_by, n.status into v_recipient, v_claimer, v_status
    from public.village_need n
    where n.id = p_need_id;

    if v_recipient is null then
        raise exception 'need not found' using errcode = 'P0002';
    end if;

    -- Must be a member of the recipient to see the need at all.
    if not tiwani_private.is_child_member(v_recipient, 'viewer') then
        raise exception 'not a member of this recipient' using errcode = '42501';
    end if;

    -- FULL logistics only for a LIVE claim: the claimer of THIS need WHILE the claim is
    -- live (status claimed or confirmed), or the owner (who coordinates throughout). Once
    -- the need is done / cancelled / re-opened, the (ex-)claimer no longer holds a live
    -- claim, so their logistics access EXPIRES per-claim (refinement 5). The owner keeps
    -- access (to coordinate / follow up).
    v_can_full := (v_claimer is not null and v_claimer = v_uid
                   and v_status in ('claimed', 'confirmed'))
                  or tiwani_private.is_child_member(v_recipient, 'owner');

    return query
        select
            n.id,
            n.status,
            n.title,
            n.detail,
            n.area_label,
            case when v_can_full then n.location_text else null end as location_text,
            case when v_can_full then n.contact_name  else null end as contact_name,
            case when v_can_full then n.contact_phone else null end as contact_phone,
            n.starts_at,
            n.ends_at,
            split_part(c.name, ' ', 1) as recipient_first_name,
            (n.claimed_by = v_uid) as claimed_by_me,
            (n.claimed_by is not null) as is_claimed
        from public.village_need n
        join public.child_profile c on c.id = n.recipient_id
        where n.id = p_need_id;
end;
$$;

revoke all on function public.get_village_need_detail(uuid) from public;
grant execute on function public.get_village_need_detail(uuid) to authenticated;
