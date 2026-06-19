-- Migration 0020: attach the recipient's Continuity Card to a Village need, visible ONLY
-- to the helper who CLAIMS that need (or the owner). The feature-decision shape
-- (Docs/FeatureDecisions.md 2026-06-17, psychiatrist + DPO BOTH refine-and-approve): it
-- SURFACES an artifact that already exists and is already shareable (the Continuity Card,
-- first-name-only, non-clinical, expiring, revocable) to a TIGHTER audience (the one live
-- claimer) than the status quo (every villager-viewer can already read the shared card via
-- /sharing). It is a data-minimisation IMPROVEMENT, authors NO new content, and adds NO new
-- free-text field.
--
-- !!! PENDING OWNER APPLY (the 0015 / 0017 posture) !!! The owner applies it on the
-- direct-Postgres path (DATABASE_URL + asyncpg), NOT on Render and NOT from the app, then
-- reloads PostgREST (NOTIFY pgrst, 'reload schema') so the new column + RPCs are visible.
-- Until applied, the card-on-task route returns nothing; the feature is ALSO gated OFF in
-- code behind CARD_ON_TASK_ENABLED (app/engines/village/flag.py), so it stays dormant until
-- the human DPO + psychiatrist sign-off + the sharing DPIA extension clear.
--
-- THE LOCKED CONSTRAINTS this migration encodes (FeatureDecisions.md; clinical C1-C11 + DPO
-- L1-L6 converge):
--   * Per-need, default-OFF (card_attached defaults false; only an explicit attach sets it).
--   * Claimer-only + occurrence-scoped, enforced in SQL: the card resolves ONLY to the LIVE
--     claimer (claimed_by = caller AND status in claimed/confirmed) or the owner, the SAME
--     v_can_full gate as the per-claim logistics in get_village_need_detail. A dropped /
--     done / cancelled claim no longer resolves the card (access expires per-occurrence).
--   * Key off the CARD-SHARE consent (share_consent), NOT the village-logistics consent: an
--     attach requires (and records, with the governed text, verbatim) an active share_consent
--     for the recipient. The village consent alone does NOT unlock the card.
--   * Safe card only: the card resolves through the EXISTING get_recipient_card_for_member
--     ceiling (first-name-only, non-clinical, the freshness/staleness line), never a second
--     reader and never the profile / LCI / alerts / pulse.
--   * No new free-text ingress (attach is a boolean; there is no "note to the helper" field).
--   * No contribution metric (no per-helper "viewed the card" count anywhere).
--
-- ADDITIVE: one nullable-defaulted column on village_need, one widened CHECK on the audit
-- action, a recreated create_village_need (drop old signature -> new signature with the
-- attach + the card-consent gate), and one new read RPC. It reuses get_recipient_card_for_member
-- (0016) and tiwani_private.is_child_member (0015); it redefines neither.

-- =====================================================================
-- 1. village_need.card_attached -- the per-need attach flag (default OFF).
-- =====================================================================
alter table public.village_need
    add column if not exists card_attached boolean not null default false;

-- =====================================================================
-- 2. Widen the audit action CHECK to include 'card_attached' (the append-only trail records
--    that the owner attached the card, for governance). Drop + re-add the named constraint.
-- =====================================================================
alter table public.village_need_event
    drop constraint if exists village_need_event_action_check;
alter table public.village_need_event
    add constraint village_need_event_action_check
    check (action in
           ('posted', 'claimed', 'confirmed', 'done',
            'dropped', 'cancelled', 're_broadcast', 'card_attached'));

-- =====================================================================
-- 3. create_village_need(...) -- recreated with p_attach_card + the CARD-SHARE consent gate.
--
-- The old 9-arg signature is dropped and replaced with the 11-arg one (p_attach_card +
-- p_card_consent_text). The village-consent gate is unchanged. When p_attach_card is true a
-- SECOND gate applies: an ACTIVE share_consent (the card-share consent, 0016) must exist for
-- the recipient; if none exists yet, the governed p_card_consent_text is recorded verbatim as
-- that consent (the owner saw + confirmed the card-share line in the app), and if no text is
-- supplied the post is refused (errcode P0001, a distinct message the route maps to a
-- card-consent prompt). card_attached is stored, and a 'card_attached' audit event is added.
-- =====================================================================
drop function if exists public.create_village_need(uuid, text, text, text, text, text, text, timestamptz, timestamptz);

create or replace function public.create_village_need(
    p_recipient_id      uuid,
    p_title             text,
    p_detail            text,
    p_location_text     text,
    p_area_label        text,
    p_contact_name      text,
    p_contact_phone     text,
    p_starts_at         timestamptz,
    p_ends_at           timestamptz,
    p_attach_card       boolean default false,
    p_card_consent_text text default null
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

    -- VILLAGE CONSENT GATE (unchanged): an active village consent must exist for any broadcast.
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

    -- CARD-SHARE CONSENT GATE (only when attaching the card; the DPO's load-bearing point):
    -- keyed off share_consent (the "share the support card" consent), NOT the village consent.
    -- If no active card-share consent exists, record the governed text the owner confirmed in
    -- the app (verbatim); if no text was supplied, refuse with a distinct, route-mappable error.
    if p_attach_card then
        if not exists (
            select 1 from public.share_consent c
            where c.recipient_id = p_recipient_id and c.revoked_at is null
        ) then
            if p_card_consent_text is null or length(btrim(p_card_consent_text)) = 0 then
                raise exception 'card sharing consent not recorded for this recipient'
                    using errcode = 'P0001';
            end if;
            -- Record the card-share consent verbatim (subject_kind 'child' is the MVP; the D8
            -- adult capacity-framed variant is a follow-up gated with the rest of the feature).
            insert into public.share_consent (recipient_id, consented_by, subject_kind, consent_text)
            values (p_recipient_id, v_uid, 'child', p_card_consent_text);
        end if;
    end if;

    insert into public.village_need
        (recipient_id, status, title, detail, location_text, area_label,
         contact_name, contact_phone, starts_at, ends_at, created_by, card_attached)
    values
        (p_recipient_id, 'open', p_title, p_detail, p_location_text, p_area_label,
         p_contact_name, p_contact_phone, p_starts_at, p_ends_at, v_uid, coalesce(p_attach_card, false))
    returning id into v_id;

    insert into public.village_need_event (need_id, action, actor)
    values (v_id, 'posted', v_uid);

    if coalesce(p_attach_card, false) then
        insert into public.village_need_event (need_id, action, actor)
        values (v_id, 'card_attached', v_uid);
    end if;

    return v_id;
end;
$$;

revoke all on function public.create_village_need(uuid, text, text, text, text, text, text, timestamptz, timestamptz, boolean, text) from public;
grant execute on function public.create_village_need(uuid, text, text, text, text, text, text, timestamptz, timestamptz, boolean, text) to authenticated;

-- =====================================================================
-- 4. get_village_need_card(need_id) -- the claimer-only, occurrence-scoped CARD read.
--
-- SECURITY DEFINER. Returns the recipient's safe Continuity Card (as jsonb) ONLY when ALL of:
--   * the caller is an ACTIVE member of the need's recipient (the read floor), AND
--   * the need has card_attached = true, AND
--   * the caller is the LIVE claimer of THIS need (claimed_by = caller AND status in
--     claimed/confirmed) OR the owner of the recipient (the SAME v_can_full gate as the
--     per-claim logistics) -- so a non-claimer, a dropped/done/ex-claimer, or a revoked
--     member resolves NOTHING.
-- The card content is resolved LIVE through the existing get_recipient_card_for_member ceiling
-- (0016), so the card's 30-day expiry + soft-revoke kill the attached view exactly as they
-- kill every other share (it returns null for a revoked / expired / absent card). It is the
-- ONLY card reader (no second serializer); it never reaches the profile / LCI / alerts / pulse.
-- Returns null when not allowed / no card, which the route maps to "no card available" (404),
-- never a 200 with empty (gate the read, do not show-then-hide).
-- =====================================================================
create or replace function public.get_village_need_card(p_need_id uuid)
returns jsonb
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
    v_attached   boolean;
    v_can_full   boolean;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select n.recipient_id, n.claimed_by, n.status, n.card_attached
      into v_recipient, v_claimer, v_status, v_attached
    from public.village_need n
    where n.id = p_need_id;

    if v_recipient is null then
        return null;  -- need not found: resolve nothing (the route maps null -> 404)
    end if;

    -- Read floor: a non-member of the recipient resolves nothing.
    if not tiwani_private.is_child_member(v_recipient, 'viewer') then
        return null;
    end if;

    -- The card must be attached to THIS need.
    if not coalesce(v_attached, false) then
        return null;
    end if;

    -- Claimer-only + occurrence-scoped (the SAME gate as the per-claim logistics): the LIVE
    -- claimer of this need, or the owner. A dropped / done / cancelled claim no longer holds a
    -- live claim, so the (ex-)claimer resolves nothing; a non-claiming member resolves nothing.
    v_can_full := (v_claimer is not null and v_claimer = v_uid
                   and v_status in ('claimed', 'confirmed'))
                  or tiwani_private.is_child_member(v_recipient, 'owner');

    if not v_can_full then
        return null;
    end if;

    -- The LIVE safe card via the existing member-card ceiling (revoke + expiry honoured;
    -- first-name-only, non-clinical). Null when the recipient has no live shareable card.
    return public.get_recipient_card_for_member(v_recipient);
end;
$$;

revoke all on function public.get_village_need_card(uuid) from public;
grant execute on function public.get_village_need_card(uuid) to authenticated;
