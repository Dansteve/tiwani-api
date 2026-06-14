-- Migration 0019: a SHORT, human-typable JOIN CODE on recipient_invite (so a helper can
-- TYPE a code instead of pasting the long opaque token), built to the 2026-06-13 CTO +
-- researcher board verdict (governance/Sprints/Backlog.md, the "short typed join code" row).
--
-- !!! PENDING OWNER APPLY (not applied to production by this change; the 0013/0015/0016
-- posture) !!! The owner applies it on deploy via the direct-Postgres path (DATABASE_URL +
-- asyncpg) that applies every migration, NOT on Render and NOT from the app. Until it is
-- applied the column and the two RPCs below do not exist on the live DB; the api routes that
-- read/write through them must not ship against production before the owner applies it. Apply
-- order is strictly increasing: 0015 (the substrate) and 0016 (the sharing layer) MUST be on
-- the DB first (this migration depends on public.recipient_invite, the
-- tiwani_private.recipient_invite_state_guard trigger, and public.mint_recipient_invite from
-- 0015).
--
-- WHAT THIS IS. The opaque token (0015) is ~256-bit and impossible to type. This adds a
-- SHORT human-typable credential alongside it, on the SAME invite, with the SAME guarantees:
-- email-bound, single-use, short-lived, owner-revocable. The board's bar for a credential to
-- a vulnerable child's village:
--   - Crockford base32, 10 chars (~50 bits) from a CSPRNG (8 chars / 40-bit is a board
--     NO-GO; the entropy lives in the Python caller's secrets-based generator). The DB stores
--     the NORMALIZED code (uppercase, no dashes); the dashes in the displayed XXXXX-XXXXX are
--     cosmetic and are stripped before storage and before lookup.
--   - The email-bind is the REAL second factor (a guessed code is useless unless the attacker
--     is ALSO signed in as the bound email). The redeem-by-code RPC funnels into the SAME
--     first-wins / single-use / email-bound CORE as the token redeem; it does NOT fork it.
--   - A short code MUST be throttled: the api route that calls the by-code RPC carries the
--     same per-IP + per-token rate limiters as the token redeem (app/rate_limit.py). This
--     migration is the storage + the atomic RPCs; the throttle is enforced at the route.
--   - NO ORACLE: the by-code RPC raises ONE uniform error on EVERY failure (unknown / expired
--     / already redeemed / revoked / wrong-email), so neither the error nor (at the route) the
--     response can tell "code does not exist" from "code exists but you are not the bound
--     email". The token redeem RPC raises distinct messages (for server logs); the by-code RPC
--     deliberately does NOT, so there is no message-shape oracle even in the logs.
--
-- ADDITIVE + IDEMPOTENT (with one deliberate replace): it ADDs one nullable column (add column
-- if not exists), one partial unique index (create index if not exists), and one new redeem
-- function (create or replace); and it REPLACES the 0016 share_recipient_invite with a
-- code-aware version (drop-the-old-overload + create, so a 7-arg call cannot stay ambiguous,
-- explained at section 2). The 0015 substrate (mint_recipient_invite, redeem_recipient_invite,
-- the triggers) and every existing invite are untouched (join_code stays null on a token-only
-- invite, which the partial unique index ignores). RLS is UNCHANGED: recipient_invite keeps its
-- 0015 owner-reads / no-user-writes policies and the recipient_invite_state_guard write-once
-- trigger (join_code is set once at INSERT by the mint path and is never updated, so the BEFORE
-- UPDATE guard never sees it change).

-- =====================================================================
-- 1. recipient_invite.join_code -- the NORMALIZED short typable code.
--
-- Stored uppercase with NO dashes/spaces (the canonical form the normalizer produces), so a
-- lookup compares like-for-like and a human's case/dash/alias mistyping is forgiven in Python
-- (I/L -> 1, O -> 0) BEFORE it reaches here. Nullable: a token-only invite (the existing path,
-- and any future caller that does not attach a code) leaves it null, and the partial unique
-- index below ignores nulls, so this is fully backward compatible.
-- =====================================================================
alter table public.recipient_invite
    add column if not exists join_code text;

-- =====================================================================
-- The active-code uniqueness guard. A PARTIAL unique index over only the ACTIVE invites that
-- carry a code: a given normalized join_code resolves to AT MOST ONE invite that is still
-- live (not redeemed, not revoked). Rationale for partial over global unique:
--   - A code is a SHORT-LIVED credential. Once an invite is redeemed or revoked it is dead and
--     its code can never be used again (the redeem-by-code RPC requires redeemed_at is null and
--     revoked_at is null inside the lock), so keeping a global unique would needlessly forbid a
--     later mint from ever drawing the same 10-char code again, shrinking the usable space over
--     time for no security gain.
--   - The audit row is RETAINED (the substrate never hard-deletes an invite; soft state via
--     redeemed_at / revoked_at). A partial unique keeps the spent row AND frees its code.
--   - This mirrors the substrate's own uq_recipient_membership_active (partial unique on the
--     active rows only), so the pattern is consistent.
-- The mint RPC relies on this index to reject a (vanishingly unlikely at 50 bits) active-code
-- collision atomically: a second concurrent INSERT of the same active code raises a
-- unique_violation, which the mint surfaces as a retryable error rather than minting a duplicate.
-- =====================================================================
create unique index if not exists uq_recipient_invite_active_join_code
    on public.recipient_invite (join_code)
    where join_code is not null and redeemed_at is null and revoked_at is null;

-- =====================================================================
-- 2. share_recipient_invite(child_id, email, role, token, subject_kind, consent_text, ttl,
--    JOIN_CODE) -- the CONSENT-GATED viewer invite (0016), now CODE-AWARE.
--
-- This REPLACES the 0016 share_recipient_invite with one extra trailing param: p_join_code (the
-- pre-NORMALIZED short typable code; uppercase, no dashes; the Python caller normalized it). It
-- is added LAST with a NULL default, so the existing 7-arg call site keeps working unchanged
-- (a token-only invite passes no code and leaves join_code null, which the partial unique index
-- ignores). The body is otherwise IDENTICAL to 0016: it enforces consent FIRST (a child share
-- records the governed consent atomically before the mint; an adult share is blocked unless a
-- recorded adult consent already exists), so the 0016 invariant holds: NO invite (with or
-- without a code) is ever minted without a recorded, visible consent, atomically.
--
-- The board shortened the typable-code window to 24-72h, so the SHARING SERVICE passes
-- p_ttl_hours => 48 for a code-bearing share; the token and the code share ONE expiry, one
-- invite, one lifetime (no second expiry column to reason about). When p_join_code is provided
-- it INSERTs the invite directly (carrying both token and code) under the same owner gate the
-- substrate mint enforces, re-checked here; when it is null it delegates to the substrate's
-- mint_recipient_invite exactly as 0016 did (the token-only path, untouched).
--
-- Keeping consent atomic with the mint (rather than adding a separate consent-bypassing
-- code-mint RPC) is the load-bearing reason this REPLACES share_recipient_invite instead of
-- adding a sibling: there must be no path that mints a code-bearing invite without consent.
--
-- SECURITY DEFINER, owner-gated, search_path empty, every reference schema-qualified (the 0016
-- hardening). A duplicate ACTIVE join_code raises unique_violation (the partial index); the
-- caller treats that as a transient collision and retries with a fresh code.
--
-- OVERLOAD HYGIENE: the 0016 function had 7 params; this one adds an 8th (p_join_code). Keeping
-- BOTH overloads would make a 7-arg call AMBIGUOUS (Postgres could pick either), so we DROP the
-- old 7-arg overload first and replace it with this single 8-arg definition. The service is the
-- only caller and always passes the 8th arg (NULL for any token-only path), so there is exactly
-- one callable signature and no ambiguity. The drop is IF EXISTS (idempotent / safe to re-run).
-- =====================================================================
drop function if exists public.share_recipient_invite(uuid, text, text, text, text, text, integer);

create or replace function public.share_recipient_invite(
    p_child_id     uuid,
    p_email        text,
    p_role         text,
    p_token        text,
    p_subject_kind text,
    p_consent_text text default null,
    p_ttl_hours    integer default 168,  -- 7 days for the token-only path (0016 default)
    p_join_code    text default null      -- the short typable code (null = token-only invite)
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
    -- Owner gate (defence in depth; the substrate mint re-checks too). Only an active owner of
    -- this recipient may share it.
    if not tiwani_private.is_child_member(p_child_id, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;
    if p_subject_kind not in ('child', 'adult') then
        raise exception 'subject kind must be child or adult' using errcode = '22023';
    end if;
    if p_role not in ('viewer', 'editor') then
        raise exception 'invite role must be viewer or editor' using errcode = '22023';
    end if;

    if p_subject_kind = 'child' then
        -- The responsible adult consents now; record it atomically before the mint (0016).
        if p_consent_text is null or length(btrim(p_consent_text)) = 0 then
            raise exception 'consent text is required to share' using errcode = '22023';
        end if;
        perform public.record_share_consent(p_child_id, 'child', p_consent_text);
    else
        -- ADULT recipient: blocked unless the adult's own consent is already on record (0016).
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

    if p_join_code is null then
        -- TOKEN-ONLY (the 0016 path, untouched): delegate to the substrate mint. join_code
        -- stays null on the row, which the partial unique index ignores.
        select public.mint_recipient_invite(p_child_id, p_email, p_role, p_token, p_ttl_hours)
            into v_invite_id;
    else
        -- CODE-BEARING: insert the invite carrying BOTH the token and the normalized code, with
        -- the (shortened) 48h TTL the service passes. Same owner-gated, email-bound, role-checked
        -- shape the substrate mint uses; the partial unique index rejects an active-code clash.
        insert into public.recipient_invite
            (recipient_id, token, email, role, invited_by, expires_at, join_code)
        values
            (p_child_id,
             p_token,
             lower(p_email),
             p_role,
             v_uid,
             now() + make_interval(hours => p_ttl_hours),
             p_join_code)
        returning id into v_invite_id;
    end if;

    return v_invite_id;
end;
$$;

-- The old 7-arg overload was dropped above; this is now the ONLY share_recipient_invite. Set
-- the same grants 0016 set (revoke from public, execute to authenticated).
revoke all on function public.share_recipient_invite(uuid, text, text, text, text, text, integer, text) from public;
grant execute on function public.share_recipient_invite(uuid, text, text, text, text, text, integer, text) to authenticated;

-- =====================================================================
-- 3. redeem_recipient_invite_by_code(join_code) -- the invitee claims the invite by TYPING the
--    code. ATOMIC, first-wins, email-bound. It funnels into the SAME core as the token redeem
--    (0015 redeem_recipient_invite): resolve the active invite, then run the identical lock /
--    re-check / single-use stamp / membership create. The ONLY difference is the lookup key
--    (the normalized join_code instead of the token) and the NO-ORACLE uniform error.
--
-- NO-ORACLE (the load-bearing security property): on ANY failure reason (unknown code /
-- expired / already redeemed / revoked / not signed in as the bound email) it raises the SAME
-- error with the SAME message and the SAME sqlstate. So neither the thrown error nor the route
-- that maps it can distinguish "no such code" from "the code exists but you are not the bound
-- email". The token redeem RPC intentionally raises DISTINCT messages (for server-side logging
-- of why a token failed); the by-code RPC intentionally does NOT, because a short code is a
-- guessing surface and a per-reason message (even in logs) is an oracle. The email-bind is the
-- real second factor: a correctly-guessed code still fails unless the caller is signed in as
-- the invite's bound email.
--
-- The lookup is scoped to ACTIVE invites only (redeemed_at is null AND revoked_at is null),
-- which the partial unique index guarantees resolves to at most one row. SECURITY DEFINER (it
-- reads the invite past the owner-only RLS, because the redeemer is the invitee not the owner,
-- and writes both tables which have no user insert policy). Returns the new membership id.
-- =====================================================================
create or replace function public.redeem_recipient_invite_by_code(p_join_code text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid    uuid := auth.uid();
    v_email  text;
    v_inv    public.recipient_invite;
    v_mid    uuid;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    if p_join_code is null or length(btrim(p_join_code)) = 0 then
        -- A malformed/empty code is the SAME generic failure as an unknown one (no oracle).
        raise exception 'invite could not be redeemed' using errcode = 'P0001';
    end if;

    -- The caller's verified email (auth.users.email), lower-cased for the email-bound match.
    select lower(u.email) into v_email from auth.users u where u.id = v_uid;

    -- Resolve the ONE active invite carrying this normalized code, and LOCK it so a concurrent
    -- redeem of the same code serializes behind us (first-wins). The active-only predicate
    -- matches the partial unique index, so at most one row is found.
    select * into v_inv
    from public.recipient_invite i
    where i.join_code = p_join_code
      and i.redeemed_at is null
      and i.revoked_at is null
    for update;

    -- NO-ORACLE: every failure below raises the SAME generic error (message + sqlstate), so an
    -- attacker cannot tell "no such code" from "code exists, wrong email" from "expired".
    if v_inv.id is null then
        raise exception 'invite could not be redeemed' using errcode = 'P0001';
    end if;
    if v_inv.expires_at <= now() then
        raise exception 'invite could not be redeemed' using errcode = 'P0001';
    end if;
    if v_email is null or v_email <> v_inv.email then
        -- The email-bind: a correctly-typed code still fails unless the caller IS the bound
        -- email. Same generic error as a wrong code (the second factor never reveals itself).
        raise exception 'invite could not be redeemed' using errcode = 'P0001';
    end if;

    -- Single-use stamp (inside the lock): a replay of this code now finds redeemed_at set and,
    -- because the active-only lookup above excludes a redeemed row, resolves to nothing.
    update public.recipient_invite
       set redeemed_at = now(),
           redeemed_by = v_uid
     where id = v_inv.id;

    -- Create the membership at the invited role, attributing the grant to the inviter. If an
    -- active membership already exists for this (recipient, user) reuse it (the active-unique
    -- index), exactly as the token redeem does.
    select m.id into v_mid
    from public.recipient_membership m
    where m.recipient_id = v_inv.recipient_id
      and m.user_id = v_uid
      and m.revoked_at is null;

    if v_mid is not null then
        return v_mid;
    end if;

    insert into public.recipient_membership
        (recipient_id, user_id, role, granted_by)
    values
        (v_inv.recipient_id, v_uid, v_inv.role, v_inv.invited_by)
    returning id into v_mid;

    return v_mid;
end;
$$;

revoke all on function public.redeem_recipient_invite_by_code(text) from public;
grant execute on function public.redeem_recipient_invite_by_code(text) to authenticated;
