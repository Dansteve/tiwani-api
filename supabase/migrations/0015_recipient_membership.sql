-- Migration 0015: recipient_membership + recipient_invite (the shared RLS substrate
-- for per-recipient sharing) + the is_child_member() SECURITY DEFINER helper + atomic
-- mint/redeem invite RPCs.
--
-- !!! PENDING OWNER APPLY (not applied to production by this change; same posture as
-- 0013) !!! The owner applies it via the direct-Postgres path (DATABASE_URL + asyncpg)
-- that applies every migration, NOT on Render and NOT from the app. Until it is applied
-- the tables and functions below do not exist on the live DB; the feature teams that
-- consume this substrate (Shared-Child sharing, the Village Hub) must not ship reads
-- against it before the owner applies this migration.
--
-- (Numbering: 0014 is intentionally skipped. The next migration number after the
-- committed 0013 was reserved for an in-flight account follow-up; this substrate takes
-- 0015 per the feature decision so the two parallel tracks do not collide on a number.
-- The apply-order chain is still strictly increasing.)
--
-- WHAT THIS IS. Two feature decisions converge on ONE primitive (Docs/FeatureDecisions.md):
--   - Shared Child / Co-Coordinator access (the REFINE entry, refinements 2/3/4/8): a
--     membership/role table is the RLS primitive NOW (not single-owner), the single-owner
--     case is just one row with role='owner'.
--   - Village Delegation Hub (the APPROVED next-phase entry, refinement 4 + its hard
--     precondition): village members get real accounts under RLS, invited email-bound,
--     single-use, owner-revocable, redeemed via an atomic SECURITY DEFINER RPC.
-- The board direction is explicit: build the substrate ONCE, the Hub is the SECOND
-- consumer. So this migration is that shared substrate and nothing feature-specific.
--
-- THE THREE LOAD-BEARING PROPERTIES (the board's "RLS done right", refinement 3 + 4):
--   1. A SECURITY DEFINER membership check in a NON-EXPOSED schema, so the membership
--      RLS policies can ask "is the caller a member of this recipient" WITHOUT a policy
--      on recipient_membership reading recipient_membership again (the recursive-policy
--      trap, which Postgres rejects at query time). The helper runs past RLS with the
--      definer's rights and re-derives the caller from auth.uid() itself, so it is safe.
--   2. SPLIT read vs write. READS are allowed to any ACTIVE member (revoked_at is null,
--      role >= viewer). WRITES to the membership/invite tables are OWNER-ONLY at the DB
--      AND only through the RPCs below: there is NO user INSERT policy on either table,
--      so the only path that writes a membership or a token is a SECURITY DEFINER RPC
--      that checks ownership first. A viewer's id is NEVER OR-ed into a broad owner
--      policy (that would hand a viewer the owner's full surface).
--   3. ATTRIBUTION is separate from AUTHORITY (refinement 8). child_profile.user_id is
--      the immutable creator (who created what); the OWNER ROLE (who can edit/grant now)
--      is a recipient_membership row with role='owner'. granted_by records who granted a
--      membership. So a transferable owner role never rewrites the historical creator.
--
-- INVITES match the bar for a vulnerable person's data (refinement 4): email-bound (not a
-- public reusable code), single-use (redeemed_at stamped, first-redeem-wins), short-lived
-- (expires_at), owner-revocable (revoked_at), and minted/redeemed ONLY by atomic SECURITY
-- DEFINER RPCs (the 0007 card-token precedent). A revoked or used or expired token reads
-- as nothing and cannot be replayed.
--
-- ADDITIVE and IDEMPOTENT: it creates new tables, a new non-exposed schema, and new
-- functions; it drops or alters NO existing object. gen_random_uuid() is core Postgres
-- (Supabase runs 15+); no extension is needed. Schema is owned by this migration only
-- (no create_all, no live table edits).

-- =====================================================================
-- 0. The non-exposed schema for the membership-check helper.
-- A schema PostgREST does not expose (it serves `public` and `graphql_public`), so
-- is_child_member is reachable from inside RLS policies and the RPCs but is NOT a
-- callable api endpoint. Revoke the broad default; the helper grants EXECUTE explicitly.
-- =====================================================================
create schema if not exists tiwani_private;

revoke all on schema tiwani_private from public;
grant usage on schema tiwani_private to authenticated;
grant usage on schema tiwani_private to anon;

-- =====================================================================
-- recipient_membership
-- One row = one user's access to one care recipient, at one role. The single-owner
-- case (today's reality: the creator) is exactly one row with role='owner'. A shared
-- recipient gains viewer / editor rows. revoked_at soft-revokes (the 0008 precedent):
-- the audit row is kept, never deleted, and a revoked membership grants nothing.
-- =====================================================================
create table if not exists public.recipient_membership (
    id                  uuid primary key default gen_random_uuid(),

    -- The care recipient this membership is for. (child_profile is the general
    -- care-recipient table per D8.) Cascade so closing a recipient removes its roster.
    recipient_id        uuid not null references public.child_profile (id) on delete cascade,

    -- The user this membership grants access TO. Cascade on auth.users delete so a
    -- closed account leaves no dangling membership.
    user_id             uuid not null references auth.users (id) on delete cascade,

    -- The role. owner = full edit + the ONLY role that grants/revokes (and the only role
    -- whose membership the write policies/RPCs honour). editor = a co-coordinator who
    -- contributes (RESERVED now so a separated co-parent is not permanently a viewer).
    -- viewer = read-only (the Shared-Child MVP role; the Village Hub helper role).
    role                text not null check (role in ('owner', 'viewer', 'editor')),

    -- Who granted this membership (attribution on the grant itself). Nullable: the
    -- bootstrap owner row (created when a recipient is first created) is self-granted /
    -- system-granted and has no granting user. NOT the same as authority.
    granted_by          uuid references auth.users (id) on delete set null,

    granted_at          timestamptz not null default now(),

    -- Soft-revoke marker: null = active, a timestamp = revoked at that instant. A revoked
    -- membership is retained for audit (who could see what, when) and grants nothing: the
    -- is_child_member helper and the read policy both require revoked_at is null.
    revoked_at          timestamptz,

    created_at          timestamptz not null default now()
);

-- At most ONE ACTIVE membership per (recipient, user): a user is not simultaneously a
-- viewer and an editor of the same recipient. Partial unique (only active rows) so a
-- revoked row is kept and a fresh membership can be granted later. This also makes the
-- owner row a single active owner per (recipient, user); the single-transferable-owner
-- rule is enforced in the grant RPC, not as a table constraint (a recipient can transit
-- through states the RPC controls).
create unique index if not exists uq_recipient_membership_active
    on public.recipient_membership (recipient_id, user_id)
    where revoked_at is null;

-- Read patterns: "who is in this recipient's roster" and "what can this user see".
create index if not exists idx_recipient_membership_recipient
    on public.recipient_membership (recipient_id);

create index if not exists idx_recipient_membership_user
    on public.recipient_membership (user_id);

-- =====================================================================
-- recipient_invite
-- An email-bound, single-use, short-lived, owner-revocable invite to JOIN a recipient at
-- a role. The opaque token is the link's only secret (minted with a strong source in the
-- RPC). The membership is created when (and only when) the invited email redeems the
-- token through the redeem RPC. Same careful-token posture as card_record (0007): a token
-- holder is unauthenticated for the lookup, so there is no table-select path to a token;
-- the only writers are the SECURITY DEFINER RPCs.
-- =====================================================================
create table if not exists public.recipient_invite (
    id                  uuid primary key default gen_random_uuid(),

    recipient_id        uuid not null references public.child_profile (id) on delete cascade,

    -- The opaque single secret in the invite link. UNIQUE so a token resolves to at most
    -- one invite. Generated with secrets.token_urlsafe in the RPC caller's mint path.
    token               text not null unique,

    -- EMAIL-BOUND: the invite is for THIS email only (refinement 4: not a public reusable
    -- code). Stored lower-cased by the mint RPC; redeem requires the caller's auth email
    -- to match, so a leaked link cannot be redeemed by a different account.
    email               text not null,

    -- The role this invite grants on redemption. Owner is NOT invitable: owner transfer
    -- is a separate deliberate action, never an invite, so the check below bars it.
    role                text not null check (role in ('viewer', 'editor')),

    -- The owner who minted the invite (the granting user, carried onto the membership's
    -- granted_by at redeem time). on delete cascade: if that user is gone, the pending
    -- invite goes too.
    invited_by          uuid not null references auth.users (id) on delete cascade,

    -- Single-use: stamped the instant the invite is redeemed. A second redeem of the same
    -- token finds redeemed_at already set and fails (first-redeem-wins, the replay guard).
    redeemed_at         timestamptz,
    -- Who redeemed it (the account that claimed the invite). Null until redeemed.
    redeemed_by         uuid references auth.users (id) on delete set null,

    -- Owner-revocable: the owner can kill a pending invite before it is redeemed.
    revoked_at          timestamptz,

    -- Short-lived: the redeem RPC requires now() < expires_at. Set by the mint RPC.
    expires_at          timestamptz not null,

    created_at          timestamptz not null default now()
);

create index if not exists idx_recipient_invite_recipient
    on public.recipient_invite (recipient_id);

create index if not exists idx_recipient_invite_token
    on public.recipient_invite (token);

-- =====================================================================
-- 1. is_child_member(child_id, min_role) -- the SECURITY DEFINER membership check.
--
-- Lives in tiwani_private (non-exposed) and runs SECURITY DEFINER, the two things that
-- break the recursive-policy trap: a policy ON recipient_membership can call this to ask
-- "is the caller an active member of recipient X at >= min_role" WITHOUT triggering
-- recipient_membership's own RLS (the function reads past RLS with the definer's rights),
-- so there is no policy-evaluates-policy recursion. It re-derives the caller from
-- auth.uid() itself (never a passed-in user id), so a caller cannot ask about anyone but
-- themselves; an unauthenticated caller (auth.uid() is null) is never a member.
--
-- min_role is a THRESHOLD on the role ladder owner(3) > editor(2) > viewer(1):
--   - min_role='viewer'  -> true for any active member (viewer, editor, or owner)
--   - min_role='editor'  -> true for an active editor or owner
--   - min_role='owner'   -> true only for an active owner
-- so a read policy uses 'viewer' (any member reads) and a write policy uses 'owner'.
-- Only ACTIVE memberships count (revoked_at is null), so an owner-revoke stops resolving
-- on the very next request.
--
-- search_path is pinned empty and every reference is schema-qualified (the standard
-- SECURITY DEFINER hardening, same as get_card_by_token). It is STABLE (one consistent
-- read per statement). EXECUTE is granted to authenticated (RLS callers + the RPCs);
-- anon never has a membership, but the grant lets an anon-context policy evaluate to
-- false rather than error.
-- =====================================================================
create or replace function tiwani_private.is_child_member(p_child_id uuid, p_min_role text)
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
    select exists (
        select 1
        from public.recipient_membership m
        where m.recipient_id = p_child_id
          and m.user_id = auth.uid()
          and m.revoked_at is null
          and auth.uid() is not null
          and case p_min_role
                  when 'owner'  then m.role = 'owner'
                  when 'editor' then m.role in ('owner', 'editor')
                  when 'viewer' then m.role in ('owner', 'editor', 'viewer')
                  else false
              end
    );
$$;

revoke all on function tiwani_private.is_child_member(uuid, text) from public;
grant execute on function tiwani_private.is_child_member(uuid, text) to authenticated;
grant execute on function tiwani_private.is_child_member(uuid, text) to anon;

-- =====================================================================
-- 2. Row Level Security on recipient_membership: SPLIT read vs write.
--
-- READ (select): allowed to any ACTIVE member of the recipient (is_child_member at the
-- 'viewer' threshold). So an owner sees the whole roster, and a viewer/editor sees the
-- roster of a recipient they belong to (the "who can see [name]" list the board requires
-- is just a select for members). A non-member reads NOTHING. A revoked member is not an
-- active member, so it reads nothing.
--
-- WRITE: there is NO user INSERT policy and NO user-broad UPDATE/DELETE policy that a
-- viewer could ride. Membership writes happen ONLY through the SECURITY DEFINER RPCs
-- below (grant / revoke), which check OWNER first. The single OWNER-only UPDATE policy
-- here exists so the owner-only revoke RPC (which runs SECURITY INVOKER under the owner's
-- session) can stamp revoked_at; it is guarded by is_child_member(... 'owner') on BOTH
-- the using and the with check, and it forbids changing the identity columns, so it can
-- only flip revoked_at on a row of a recipient the caller owns. A viewer's id is NEVER
-- OR-ed into this policy.
-- =====================================================================
alter table public.recipient_membership enable row level security;

drop policy if exists recipient_membership_select_member on public.recipient_membership;
create policy recipient_membership_select_member
    on public.recipient_membership
    for select
    using (tiwani_private.is_child_member(recipient_id, 'viewer'));

drop policy if exists recipient_membership_update_owner on public.recipient_membership;
create policy recipient_membership_update_owner
    on public.recipient_membership
    for update
    using (tiwani_private.is_child_member(recipient_id, 'owner'))
    with check (tiwani_private.is_child_member(recipient_id, 'owner'));

-- No INSERT policy and no DELETE policy by design: a membership is born only from the
-- grant RPC (or the bootstrap RPC) and is never hard-deleted (soft-revoke keeps the
-- audit row). The RPCs are SECURITY DEFINER and do the ownership check themselves.

-- =====================================================================
-- 3. Row Level Security on recipient_invite: owner-reads, no user writes.
--
-- READ: an OWNER of the recipient may list its invites (to see and revoke pending ones).
-- A viewer/editor cannot read invites (the token is a secret; only the owner manages
-- them). A non-member reads nothing. The unauthenticated token lookup does NOT go through
-- a select (it goes through the redeem RPC), so no anon select policy is needed or wanted.
--
-- WRITE: NO user INSERT policy (mint is an RPC), NO user DELETE policy. A single
-- OWNER-only UPDATE policy lets the owner-revoke RPC stamp revoked_at on an invite of a
-- recipient the caller owns; the redeem path stamps redeemed_at/redeemed_by from inside
-- the SECURITY DEFINER redeem RPC (past RLS), because the redeemer is the invitee, not the
-- owner, and must not get a broad write policy.
-- =====================================================================
alter table public.recipient_invite enable row level security;

drop policy if exists recipient_invite_select_owner on public.recipient_invite;
create policy recipient_invite_select_owner
    on public.recipient_invite
    for select
    using (tiwani_private.is_child_member(recipient_id, 'owner'));

drop policy if exists recipient_invite_update_owner on public.recipient_invite;
create policy recipient_invite_update_owner
    on public.recipient_invite
    for update
    using (tiwani_private.is_child_member(recipient_id, 'owner'))
    with check (tiwani_private.is_child_member(recipient_id, 'owner'));

-- =====================================================================
-- 4. bootstrap_recipient_owner(child_id) -- mint the creator's owner membership.
--
-- When a recipient is created, the creator needs the owner row that the new membership
-- RLS keys on (otherwise the creator, whose access today is child_profile.user_id, would
-- not be a "member" and the membership-scoped reads would return them nothing). This RPC
-- is the single, controlled way to create that first owner row. It is idempotent: if an
-- active owner already exists for (child, caller) it returns that id rather than minting a
-- duplicate (so re-running, or a create retried, is safe).
--
-- SECURITY DEFINER (writes past the no-insert-policy table) but it checks that the CALLER
-- actually OWNS the child_profile (child_profile.user_id = auth.uid()) before writing, so
-- only the creator can bootstrap their own owner row, and only for a child they created.
-- =====================================================================
create or replace function public.bootstrap_recipient_owner(p_child_id uuid)
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

    -- The caller must be the creator of this child_profile (attribution = the seed of the
    -- first owner role; thereafter ownership is the membership row).
    if not exists (
        select 1 from public.child_profile c
        where c.id = p_child_id and c.user_id = v_uid
    ) then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;

    -- Idempotent: reuse an existing active owner row for this caller.
    select m.id into v_id
    from public.recipient_membership m
    where m.recipient_id = p_child_id
      and m.user_id = v_uid
      and m.role = 'owner'
      and m.revoked_at is null;

    if v_id is not null then
        return v_id;
    end if;

    insert into public.recipient_membership (recipient_id, user_id, role, granted_by)
    values (p_child_id, v_uid, 'owner', v_uid)
    returning id into v_id;

    return v_id;
end;
$$;

revoke all on function public.bootstrap_recipient_owner(uuid) from public;
grant execute on function public.bootstrap_recipient_owner(uuid) to authenticated;

-- =====================================================================
-- 5. mint_recipient_invite(child_id, email, role, ttl_hours) -- owner mints an invite.
--
-- ATOMIC owner-only mint (the 0007 token precedent): one statement INSERTs the invite
-- ONLY when the caller is an active owner of the recipient (the WHERE on the select that
-- feeds the insert is the gate), then returns the fresh token. SECURITY DEFINER so it can
-- write the no-user-insert-policy table, but it derives the owner from auth.uid() and
-- requires owner membership, so a non-owner mints nothing.
--
-- The invite is email-bound (lower-cased), single-use (redeemed_at null until claimed),
-- short-lived (expires_at = now() + ttl), owner-revocable (revoked_at). The token is
-- passed in (generated by the caller with secrets.token_urlsafe, the same as the card
-- token) so the strong-randomness source stays in Python; the RPC enforces uniqueness via
-- the table's UNIQUE(token). role is restricted to viewer/editor by the column check
-- (owner is never invited).
-- =====================================================================
create or replace function public.mint_recipient_invite(
    p_child_id uuid,
    p_email    text,
    p_role     text,
    p_token    text,
    p_ttl_hours integer default 168  -- 7 days, the card-link order of magnitude
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

    -- Owner gate: only an ACTIVE owner of this recipient may mint an invite for it.
    if not tiwani_private.is_child_member(p_child_id, 'owner') then
        raise exception 'not the owner of this recipient' using errcode = '42501';
    end if;

    if p_role not in ('viewer', 'editor') then
        raise exception 'invite role must be viewer or editor' using errcode = '22023';
    end if;

    insert into public.recipient_invite
        (recipient_id, token, email, role, invited_by, expires_at)
    values
        (p_child_id,
         p_token,
         lower(p_email),
         p_role,
         v_uid,
         now() + make_interval(hours => p_ttl_hours))
    returning id into v_id;

    return v_id;
end;
$$;

revoke all on function public.mint_recipient_invite(uuid, text, text, text, integer) from public;
grant execute on function public.mint_recipient_invite(uuid, text, text, text, integer) to authenticated;

-- =====================================================================
-- 6. redeem_recipient_invite(token) -- the invitee claims the invite. ATOMIC, first-wins.
--
-- The invited user (now signed in) redeems their token. SECURITY DEFINER so it can read
-- the invite past RLS (the invitee is NOT the owner, so they cannot select the invite) and
-- write both tables (no user insert policy). It is ATOMIC and FIRST-REDEEM-WINS:
--   - it locks the matching invite row FOR UPDATE and re-checks live/unused/unrevoked
--     inside the lock, so two concurrent redeems cannot both succeed (the second sees
--     redeemed_at already set and fails),
--   - it requires the caller's auth email to match the invite's email (EMAIL-BOUND: a
--     leaked link is useless to a different account),
--   - it stamps redeemed_at + redeemed_by (single-use; the row can never be replayed),
--   - it creates (or re-activates) the recipient_membership at the invite's role, with
--     granted_by = the inviter, attributing the grant.
-- A token that is unknown, expired, already redeemed, or revoked raises (the route maps it
-- to a friendly 4xx); a wrong-email caller raises. Returns the new membership id.
--
-- The membership upsert respects the active-unique index: if a (revoked) membership row
-- exists for this (recipient, user) it inserts a fresh active one (the old revoked row is
-- kept for audit); the partial unique only covers active rows, so this is safe.
-- =====================================================================
create or replace function public.redeem_recipient_invite(p_token text)
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

    -- The caller's verified email (auth.users.email), lower-cased for the email-bound match.
    select lower(u.email) into v_email from auth.users u where u.id = v_uid;

    -- Lock the invite row so a concurrent redeem of the same token serializes behind us;
    -- the re-checks below then run against the locked, current row (first-wins).
    select * into v_inv
    from public.recipient_invite i
    where i.token = p_token
    for update;

    if v_inv.id is null then
        raise exception 'invite not found' using errcode = 'P0002';
    end if;
    if v_inv.revoked_at is not null then
        raise exception 'invite revoked' using errcode = 'P0001';
    end if;
    if v_inv.redeemed_at is not null then
        raise exception 'invite already used' using errcode = 'P0001';
    end if;
    if v_inv.expires_at <= now() then
        raise exception 'invite expired' using errcode = 'P0001';
    end if;
    if v_email is null or v_email <> v_inv.email then
        raise exception 'invite is for a different email' using errcode = '42501';
    end if;

    -- Single-use stamp (inside the lock): a replay of this token now sees redeemed_at set.
    update public.recipient_invite
       set redeemed_at = now(),
           redeemed_by = v_uid
     where id = v_inv.id;

    -- Create the membership at the invited role, attributing the grant to the inviter.
    -- If an active membership already exists for this (recipient, user) (e.g. re-invited
    -- while still active), reuse it rather than violating the active-unique index.
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

revoke all on function public.redeem_recipient_invite(text) from public;
grant execute on function public.redeem_recipient_invite(text) to authenticated;
