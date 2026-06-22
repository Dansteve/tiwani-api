-- Migration 0021: fix the card-on-task card-share consent gate in create_village_need (PROD-DOWN HOTFIX).
--
-- BUG: create_village_need (migration 0020) gated the CARD-SHARE consent with
--     select 1 from public.share_consent c
--     where c.recipient_id = p_recipient_id and c.revoked_at is null
-- but public.share_consent (migration 0016) is APPEND-ONLY and has NO revoked_at column (only the
-- VILLAGE consent table, recipient_village_consent, has one). So posting a need WITH THE CARD ATTACHED
-- (p_attach_card = true) raised "column c.revoked_at does not exist" (SQLSTATE 42703), which surfaced as
-- an unhandled 500; because the 500 path carries no CORS header, the browser reported it as a misleading
-- "Origin not allowed by Access-Control-Allow-Origin" error. The clause was a copy-paste from the
-- village-consent check just above it.
--
-- FIX: drop the erroneous `and c.revoked_at is null` from the share_consent existence check ONLY. An
-- existing share_consent row IS the recorded card-share consent (the table is append-only; it is never
-- revoked here), so existence is the correct gate. The village-consent check (recipient_village_consent,
-- which DOES have revoked_at) is unchanged. The function body is otherwise byte-identical to 0020.
--
-- Idempotent: create or replace + a re-assert of the execute grant. The signature is unchanged, so
-- PostgREST needs no schema reload (it resolves the function by name + args, both unchanged).

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

    -- VILLAGE CONSENT GATE (unchanged): recipient_village_consent HAS revoked_at.
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

    -- CARD-SHARE CONSENT GATE (FIXED): share_consent is append-only (no revoked_at); an existing row IS
    -- the recorded card-share consent, so existence is the gate. Else record the at-attach consent text.
    if p_attach_card then
        if not exists (
            select 1 from public.share_consent c
            where c.recipient_id = p_recipient_id
        ) then
            if p_card_consent_text is null or length(btrim(p_card_consent_text)) = 0 then
                raise exception 'card sharing consent not recorded for this recipient'
                    using errcode = 'P0001';
            end if;
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

revoke all on function public.create_village_need(
    uuid, text, text, text, text, text, text, timestamptz, timestamptz, boolean, text
) from public;
grant execute on function public.create_village_need(
    uuid, text, text, text, text, text, text, timestamptz, timestamptz, boolean, text
) to authenticated;
