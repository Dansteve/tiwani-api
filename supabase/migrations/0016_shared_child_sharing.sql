-- Migration 0016: Shared-Child sharing (the MVP feature layer over the 0015 substrate).
--
-- !!! PENDING OWNER APPLY (not applied to production by this change; the 0013/0015
-- posture) !!! The owner applies it via the direct-Postgres path (DATABASE_URL +
-- asyncpg) that applies every migration, NOT on Render and NOT from the app. Until it
-- is applied the table and functions below do not exist on the live DB; the api routes
-- that read through them must not ship against production before the owner applies BOTH
-- 0015 (the substrate) and this migration. Apply order is strictly increasing: 0015
-- (the membership substrate) MUST be applied before 0016 (this layer depends on
-- tiwani_private.is_child_member and public.mint_recipient_invite from 0015).
--
-- WHAT THIS IS. The Shared-Child / Co-Coordinator MVP (Docs/FeatureDecisions.md, the
-- Shared-Child REFINE entry, refinements 1/5/7): a Coordinator who created a care
-- recipient can SHARE that recipient with another user as a read-only viewer. The 0015
-- substrate already provides the membership/invite tables, the is_child_member helper,
-- and the atomic owner-gated mint / first-wins redeem RPCs. This migration adds ONLY the
-- three feature-specific pieces the MVP needs on top of that substrate:
--
--   1. THE VISIBILITY CEILING (refinement 1). A viewer sees ONLY the existing Continuity
--      Card, NEVER the raw profile / LCI / alerts. The substrate gives a viewer a
--      recipient_membership row, but NOT a path to read anything: card_record's own RLS
--      (migration 0007) is owner-only (user_id = auth.uid()), so a viewer's membership
--      grants them no card read. get_recipient_card_for_member(child_id) is that one
--      capped read: a SECURITY DEFINER function that returns the recipient's latest live,
--      non-revoked Continuity Card content to an ACTIVE MEMBER (is_child_member at the
--      viewer threshold) and nothing else. It is the account-bound, attributed analogue
--      of the account-less get_card_by_token (0007/0008): same SAFE content jsonb (first
--      name only, non-clinical, already guarded at build time), gated on membership
--      instead of an opaque token. The viewer never touches child_profile, lci_snapshot,
--      alert_record, or pulse_record (those tables keep their owner-only RLS unchanged).
--
--   2. CONSENT IS FIRST-CLASS (refinement 5). share_consent records, per recipient, that
--      the responsible adult consented to the share, with the exact governed consent TEXT
--      that was shown, who consented, and the subject kind (child vs adult). It is VISIBLE
--      (any active member can read it, so it shows on the "who can see [name]" roster and
--      a capacitous adult recipient can see their own) and RETAINED (never deleted; the
--      soft posture). It is written ONLY by the SECURITY DEFINER RPC below (no user INSERT
--      policy), which checks owner first.
--
--   3. THE CONSENT-GATED SHARE RPC (refinement 5, the adult block). share_recipient_invite
--      wraps the substrate's mint_recipient_invite but FIRST enforces consent: for a CHILD
--      recipient the creating Coordinator consents as the responsible adult (the consent
--      text is recorded atomically in the same call); for an ADULT recipient the api BLOCKS
--      the share for the MVP unless a recorded adult consent ALREADY exists (explicit
--      recorded recipient consent before any token mints). So no viewer invite is ever
--      minted without a recorded, visible consent.
--
-- ADDITIVE and IDEMPOTENT: it creates one new table and three new functions; it drops or
-- alters NO existing object (card_record, child_profile, and the 0015 substrate are
-- untouched). gen_random_uuid() is core Postgres (Supabase runs 15+); no extension needed.

-- =====================================================================
-- 1. share_consent
-- One row = one recorded consent to share one care recipient. First-class, visible,
-- retained (refinement 5). The creating Coordinator consents as the responsible adult
-- for a child; an adult recipient's own recorded consent is the same shape with
-- subject_kind = 'adult'. The consent_text column stores the EXACT governed string that
-- was shown at the time (so the record is self-describing and survives a later copy
-- change); the copy lives in app/engines/sharing/copy.py and the RPC is handed the
-- shown text. No revoked_at: a consent is a historical fact (it happened); withdrawing
-- access is a membership/invite revoke, not a rewrite of the consent record.
-- =====================================================================
create table if not exists public.share_consent (
    id                  uuid primary key default gen_random_uuid(),

    -- The care recipient this consent is for. Cascade so closing the recipient removes
    -- its consent records along with its roster (0015 cascades the membership too).
    recipient_id        uuid not null references public.child_profile (id) on delete cascade,

    -- WHO recorded the consent (the owner acting; attribution on the consent itself).
    -- Cascade on auth.users delete so a closed account leaves no dangling consent.
    consented_by        uuid not null references auth.users (id) on delete cascade,

    -- Whether the responsible adult consenting is the CHILD recipient's Coordinator
    -- (the MVP path) or the ADULT recipient themselves (D8; gates the adult-share block).
    subject_kind        text not null check (subject_kind in ('child', 'adult')),

    -- The EXACT governed consent text shown and agreed (app/engines/sharing/copy.py).
    -- Stored verbatim so the record is self-describing even if the copy later changes.
    consent_text        text not null,

    created_at          timestamptz not null default now()
);

create index if not exists idx_share_consent_recipient
    on public.share_consent (recipient_id);

-- =====================================================================
-- RLS on share_consent: members read (it is part of "who can see [name]"), no user writes.
-- READ: any ACTIVE member of the recipient may read its consent records (the owner to
-- audit the share, a capacitous adult recipient to see their own consent). A non-member
-- reads nothing. WRITE: NO user INSERT / UPDATE / DELETE policy: a consent row is written
-- ONLY by record_share_consent (SECURITY DEFINER, owner-checked), and is never edited or
-- deleted (retained). So a viewer can neither forge a consent nor erase one.
-- =====================================================================
alter table public.share_consent enable row level security;

drop policy if exists share_consent_select_member on public.share_consent;
create policy share_consent_select_member
    on public.share_consent
    for select
    using (tiwani_private.is_child_member(recipient_id, 'viewer'));

-- =====================================================================
-- 2. get_recipient_card_for_member(child_id) -- the viewer's capped read (the CEILING).
--
-- Returns the recipient's LATEST live, non-revoked Continuity Card content as jsonb, but
-- ONLY to an ACTIVE MEMBER of that recipient (is_child_member at the viewer threshold),
-- and NOTHING ELSE. This is the account-bound analogue of get_card_by_token (0007/0008):
--   - membership-gated, not token-gated: the caller is an authenticated viewer/editor/
--     owner whose recipient_membership row is active (a revoked membership stops resolving
--     on the very next request, because is_child_member requires revoked_at is null);
--   - returns ONLY the SAFE content jsonb (the same first-name-only, non-clinical, already
--     guarded card content), with the read-time generated_at + is_stale merged in exactly
--     as the token read does, so the viewer sees the same staleness signal a helper sees;
--   - picks the most recent card for the recipient (order by created_at desc, limit 1)
--     that is live (expires_at > now()) AND not revoked, so an aged-out or revoked card is
--     never served; if the owner has not generated a (live) card yet, it returns NULL and
--     the route maps that to "no card yet" (a 404), NOT the profile.
-- The viewer NEVER reaches child_profile / lci_snapshot / alert_record / pulse_record:
-- those tables keep their owner-only RLS, and this function reads card_record only. It is
-- SECURITY DEFINER (so it can read card_record past its owner-only RLS) with search_path
-- pinned empty and every reference schema-qualified (the standard hardening, like
-- get_card_by_token), re-deriving the caller from auth.uid() inside is_child_member (never
-- a passed-in user id), so a caller can only ever read a recipient THEY are a member of.
-- STABLE (one consistent read per statement). EXECUTE to authenticated only: an anon
-- caller is never a member, so it would get NULL, but the read is not offered to anon.
-- =====================================================================
create or replace function public.get_recipient_card_for_member(p_child_id uuid)
returns jsonb
language sql
security definer
set search_path = ''
stable
as $$
    select c.content || jsonb_build_object(
               'generated_at', to_jsonb(c.created_at),
               'is_stale', (now() - c.created_at) > interval '30 days'
           )
    from public.card_record c
    where c.child_id = p_child_id
      and c.expires_at > now()
      and c.revoked_at is null
      -- The membership gate: only an ACTIVE member of this recipient gets any row back.
      -- Evaluated per the candidate card's recipient (c.child_id), so a non-member or a
      -- revoked member matches nothing and the function returns NULL.
      and tiwani_private.is_child_member(c.child_id, 'viewer')
    order by c.created_at desc
    limit 1;
$$;

revoke all on function public.get_recipient_card_for_member(uuid) from public;
grant execute on function public.get_recipient_card_for_member(uuid) to authenticated;

-- =====================================================================
-- 3. record_share_consent(child_id, subject_kind, consent_text) -- record a consent.
--
-- The single, controlled way to write a share_consent row. SECURITY DEFINER (writes the
-- no-insert-policy table) but it checks the CALLER is an ACTIVE OWNER of the recipient
-- before writing (is_child_member at the owner threshold), so only the responsible adult
-- (the owning Coordinator) records consent, and only for a recipient they own. Returns the
-- new consent id. subject_kind is validated against the table check. consent_text is the
-- exact governed string the api was handed (app/engines/sharing/copy.py); it is stored
-- verbatim so the record is self-describing. Used both directly (record an adult
-- recipient's consent before any adult share) and inside share_recipient_invite (record a
-- child consent atomically with the mint).
-- =====================================================================
create or replace function public.record_share_consent(
    p_child_id     uuid,
    p_subject_kind text,
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
    if not tiwani_private.is_child_member(p_child_id, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;
    if p_subject_kind not in ('child', 'adult') then
        raise exception 'subject kind must be child or adult' using errcode = '22023';
    end if;
    if p_consent_text is null or length(btrim(p_consent_text)) = 0 then
        raise exception 'consent text is required' using errcode = '22023';
    end if;

    insert into public.share_consent (recipient_id, consented_by, subject_kind, consent_text)
    values (p_child_id, v_uid, p_subject_kind, p_consent_text)
    returning id into v_id;

    return v_id;
end;
$$;

revoke all on function public.record_share_consent(uuid, text, text) from public;
grant execute on function public.record_share_consent(uuid, text, text) to authenticated;

-- =====================================================================
-- 4. share_recipient_invite(child_id, email, role, token, subject_kind, consent_text, ttl)
--    -- the CONSENT-GATED viewer invite (refinement 5, the adult block).
--
-- The MVP's single share entry point. It wraps the substrate's mint_recipient_invite but
-- enforces consent FIRST, so no viewer invite is ever minted without a recorded, visible
-- consent:
--   - CHILD recipient (subject_kind = 'child'): the creating Coordinator consents as the
--     responsible adult. The consent text MUST be supplied; it is recorded (a share_consent
--     row) atomically in the SAME call, THEN the invite is minted. So every child share
--     leaves a visible consent record.
--   - ADULT recipient (subject_kind = 'adult'): the MVP BLOCKS sharing at the api unless a
--     recorded adult consent ALREADY exists for this recipient (an explicit, prior
--     share_consent row with subject_kind = 'adult'). If none exists, it raises (the route
--     maps it to a calm 409, the capacity-framed copy). This is the "block adult-recipient
--     sharing at the api for MVP unless recorded consent exists" rule: the adult must have
--     recorded their own consent (via record_share_consent) before any token mints.
--
-- SECURITY DEFINER, owner-gated (it both records consent and mints, each owner-checked via
-- is_child_member / the substrate RPC). Atomic: the consent insert and the mint run in the
-- one function (one transaction), so a mint never happens without its consent, and a failed
-- mint rolls back the consent it would have recorded. role is restricted to viewer/editor
-- by the substrate (owner is never invited). Returns the new invite id; the caller (the
-- service) generated the opaque token with secrets.token_urlsafe (the card precedent) and
-- builds the share link from it.
-- =====================================================================
create or replace function public.share_recipient_invite(
    p_child_id     uuid,
    p_email        text,
    p_role         text,
    p_token        text,
    p_subject_kind text,
    p_consent_text text default null,
    p_ttl_hours    integer default 168  -- 7 days, the card-link order of magnitude
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid       uuid := auth.uid();
    v_invite_id uuid;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    -- Owner gate (defence in depth; the substrate RPC re-checks too). Only an active owner
    -- of this recipient may share it.
    if not tiwani_private.is_child_member(p_child_id, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;
    if p_subject_kind not in ('child', 'adult') then
        raise exception 'subject kind must be child or adult' using errcode = '22023';
    end if;

    if p_subject_kind = 'child' then
        -- The responsible adult consents now; record it atomically before the mint.
        if p_consent_text is null or length(btrim(p_consent_text)) = 0 then
            raise exception 'consent text is required to share' using errcode = '22023';
        end if;
        perform public.record_share_consent(p_child_id, 'child', p_consent_text);
    else
        -- ADULT recipient: blocked unless the adult's own consent is already on record.
        if not exists (
            select 1 from public.share_consent sc
            where sc.recipient_id = p_child_id
              and sc.subject_kind = 'adult'
        ) then
            raise exception
                'adult recipient sharing requires recorded consent first'
                using errcode = 'P0001';
        end if;
    end if;

    -- Mint the email-bound, single-use, short-lived, owner-revocable invite (the substrate
    -- RPC; it re-checks owner, lower-cases the email, restricts role to viewer/editor).
    select public.mint_recipient_invite(p_child_id, p_email, p_role, p_token, p_ttl_hours)
        into v_invite_id;

    return v_invite_id;
end;
$$;

revoke all on function public.share_recipient_invite(uuid, text, text, text, text, text, integer) from public;
grant execute on function public.share_recipient_invite(uuid, text, text, text, text, text, integer) to authenticated;
