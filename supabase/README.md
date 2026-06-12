# Supabase schema and migrations

This directory is the **single source of schema truth** for `tiwani-api`: the
Postgres tables, their Row Level Security (RLS) policies, and any seed SQL, all
expressed as ordered migrations. No table is created by `create_all` and no
table is edited live in the Supabase dashboard; every column and policy lands
here as a migration, applied and recorded (`HardRules/Api/Modules/Models.md`,
`HardRules/Api/SETUP.md`).

## Status: APPLIED TO THE PRODUCTION SUPABASE DATABASE

These migrations are **applied to the production Supabase database**, which is
the database of record. `0001`-`0008` were applied earlier (see `Docs/Deploy.md`,
which also records the seed load: 74 scenarios, 352 strategies, 44 tag-modifier
rows). `0009`, `0010`, and `0011` were applied **2026-06-12** in the orchestrated
multi-recipient go-live (their SQL banners read `APPLIED TO PRODUCTION 2026-06-12`;
the sole-child backfill was verified, 0 nulls). `0012` brings the live `waitlist`
table (originally a Supabase-dashboard live edit) under version control and is an
idempotent no-op against the production table. Migrations are applied via a direct
Postgres connection (`DATABASE_URL` + asyncpg), run locally by the owner, not on
Render.

## Relationship to the old prototype tables

The v3 tables here are now the **authoritative** schema. The clean rebuild to
PRD v3 (`Docs/Decisions.md` D2) is live: the four pre-v3 prototype routers and
their data layer were DELETED (CTO audit finding B1, see `HardRules/Api/SETUP.md`
build posture), so nothing in the running api reads the old prototype tables
(`profiles`, `children`, `chapters`, `triggers`) anymore. The only mounted
surface is `/api/v3`, backed solely by the tables in this directory.

These migrations never created, dropped, or altered the prototype tables (they
only added the v3 tables), so whether the old `profiles` / `children` /
`chapters` / `triggers` tables still PHYSICALLY exist in the production database
is not verified here. Dropping any leftover prototype tables is a **separate
cleanup to confirm** (a future drop migration), not done by anything in this
list; it has no effect on the api, which no longer references them.

## Migrations

| File | Adds | Notes |
| --- | --- | --- |
| `migrations/0001_foundation.sql` | `user_profile`, `child_profile` (the two stable v3 foundation tables), an index on `child_profile(user_id)`, a shared `set_updated_at()` trigger, and the RLS policies for both | `child_profile` is modelled as a general care recipient per `Docs/Decisions.md` D8 (the name is kept for the MVP). Both tables have RLS enabled with explicit per-operation policies keyed to `auth.uid()`. |
| `migrations/0002_seed_knowledge_base.sql` | The LCE seed reference tables `scenario_matrix`, `scenario_strategy`, `tag_modifier` (the scenario base scores + ranked strategies + per-tag dimension modifiers the engine reads), with CHECK constraints incl. the `temporal+sensory+logistical+human = stated_total` transcription guard | GLOBAL reference data, not user data: RLS enabled but read-for-authenticated, write-for-none (the versioned seed loader writes with the service-role key). Rows are written by `app/seed/write_seed_to_db`. |
| `migrations/0003_activity_record.sql` | `activity_record` (the stored LCE plan: base + final scores, total, tier, today flags, ranked strategies JSON, `scheduled_pulse_at`, optional `context_note`), indexes on `(user_id, chapter)` and `child_id`, a `total = sum of the four cells` check, the shared `set_updated_at` trigger, and RLS policies | USER data: RLS enabled with explicit per-operation policies keyed to `auth.uid()` (same pattern as `child_profile`). Written by `app/services/plans.py` (LCE step 8). |
| `migrations/0004_pulse_and_lci.sql` | `pulse_record` (one recorded Pulse per activity: `outcome_code` well/okay/difficult/skipped, optional `challenge_dimension`, the copied `chapter` + `tier_recommended`; `activity_id` UNIQUE + FK to `activity_record` with cascade) and `lci_snapshot` (the per-chapter LCI score over time: `chapter`, `score` 0-100, `taken_at`), with indexes on `(user_id, chapter)` / `(user_id, chapter, taken_at desc)`, the shared `set_updated_at` trigger on `pulse_record`, and RLS policies | USER data (§4.7 / §4.8): RLS enabled with explicit per-operation policies keyed to `auth.uid()`. `pulse_record.activity_id` UNIQUE enforces one Pulse per activity (the DB backstop to the route's 409). `lci_snapshot` is the weekly-trajectory + Task 7 history; written by `app/services/{pulse,lci}.py`. |
| `migrations/0005_alert_record.sql` | `alert_record` (the CURRENT active Erosion Alert per chapter: `level` 1/2/3, the `trigger_condition` code that fired it, the `dismissed` + `dismissed_level` state), a `(user_id, chapter)` UNIQUE that is the active-alert invariant and the post-pulse UPSERT target, an index on `(user_id, chapter)`, the shared `set_updated_at` trigger, and RLS policies | USER data (§4.9): RLS enabled with explicit per-operation policies keyed to `auth.uid()` (same pattern as `pulse_record`). A higher level REPLACES a lower one (at most one active alert per chapter); a dismissed alert returns only when the evaluation computes a strictly higher level. Evaluated after every pulse by `app/services/alerts.py`. The §4.9 copy is GOVERNED, gated on psychiatrist sign-off before launch. |
| `migrations/0006_user_profile_insert_policy.sql` | An INSERT policy on `user_profile` (`with check (auth.uid() = id)`) so the AUTHENTICATED user inserts their OWN profile row under RLS | Fixes a 42501 RLS violation: `0001` shipped `user_profile` with SELECT + UPDATE but no INSERT policy (it assumed a service-role create that was never configured). Since the PK references `auth.users(id)`, a user can only ever create the row keyed to themselves; no service-role key in the request path. Idempotent, additive, no data change. |
| `migrations/0007_card_record.sql` | `card_record` (the shareable Continuity Card, §4.6: an opaque UNIQUE `token`, the already-safe `content` jsonb, `expires_at` = created_at + 30 days; FKs to `child_profile` + `activity_record` with cascade), RLS policies, and the `SECURITY DEFINER` function `public.get_card_by_token(token)` | USER data (§4.6): RLS enabled with explicit per-operation policies keyed to `auth.uid()` (same pattern as `alert_record`). The token read is a SEPARATE careful path: a token holder is unauthenticated, so RLS returns them zero rows on a direct select; `get_card_by_token` is the only way to read a card without auth and returns ONLY the safe `content` (first name only, no clinical data), never `user_id` / `child_id` / `activity_id` / the token. Written by `app/services/cards.py`. |
| `migrations/0008_card_revoke.sql` | A nullable `card_record.revoked_at` (the soft-revoke marker: null = active, set = revoked) and a rebuilt `get_card_by_token` that returns nothing for a revoked OR expired token and merges read-time `generated_at` + computed `is_stale` (30-day freshness) onto the safe content | Backs the Card History feature (a Coordinator manages and revokes the cards they shared). SOFT revoke per the expert-review board: the row is kept as the audit trail, never dropped. Revoking sets `revoked_at`, which kills the public link immediately (the DB backstop to the app's revoke action). `is_stale` is computed against `now()` on every call, never stored. Additive, idempotent, no other object altered. |
| `migrations/0009_lci_snapshot_child_id.sql` | A nullable `lci_snapshot.child_id` (FK to `child_profile`, cascade), an index on `(user_id, child_id, chapter, taken_at desc)`, and a guarded backfill that sets `child_id` to the user's SOLE existing child | APPLIED TO PRODUCTION 2026-06-12 (multi-recipient go-live; backfill verified, 0 nulls). Part of the Multi Care Recipient backend (`Docs/FeatureDecisions.md`). The per-chapter LCI history was keyed by `(user_id, chapter)` only, so a second recipient's snapshots for the same chapter mixed into one series; `child_id` scopes every snapshot read and write to one named recipient (mirrors `activity_record`). RLS unchanged (the §4.8 owner policies already scope to `auth.uid()`). Added NULLABLE so the backfill runs first; a follow-up sets NOT NULL once verified. The service writes `child_id` on every new snapshot. |
| `migrations/0010_alert_record_child_id.sql` | A nullable `alert_record.child_id` (FK to `child_profile`, cascade), a guarded sole-child backfill, the unique-key SWAP from `(user_id, chapter)` to `(user_id, child_id, chapter)`, and a matching `(user_id, child_id, chapter)` index | APPLIED TO PRODUCTION 2026-06-12 (multi-recipient go-live; backfill verified, 0 nulls; applied after 0009). Part of the Multi Care Recipient backend (`Docs/FeatureDecisions.md`). The old `(user_id, chapter)` UNIQUE (from `0005`) would force two recipients to SHARE one alert row per chapter (B's evaluation overwrites A's, one dismissal silences both); moving the active-alert invariant to `(user_id, child_id, chapter)` keeps alerts per-recipient. The constraint swap is the one ALTER that changes an existing object, required for correctness. RLS unchanged (`child_id` is always a caller-owned child). NULLABLE for the backfill; a follow-up sets NOT NULL. |
| `migrations/0011_pulse_record_child_id.sql` | A nullable `pulse_record.child_id` (FK to `child_profile`, cascade), an index on `(user_id, child_id, chapter)`, and a guarded backfill that sets `child_id` from each pulse's OWN `activity_record` | APPLIED TO PRODUCTION 2026-06-12 (multi-recipient go-live; backfill verified, 0 nulls; applied with 0009/0010). A deliberate ADDITION to the design note's two-migration list: the LCI (§4.8) is FOLDED from `pulse_record`, which had no `child_id`, so two recipients' pulses for the same chapter would pool into one fold. A pulse provably belongs to one recipient (its activity's `child_id`), so storing it on the pulse is correct and makes `pulse_record` consistent with `activity_record` / `card_record`. RLS unchanged. NULLABLE for the backfill; a follow-up sets NOT NULL. The service writes `child_id` on every new pulse. |
| `migrations/0012_waitlist.sql` | The `waitlist` table (`email`, `contexts text[]`, `source`, `created_at`) documented AS IT EXISTS in production, RLS enabled with an anon-INSERT-only policy, and the minimal `grant insert ... to anon` | VERSION-CONTROL ONLY (owner decision 2026-06-12), an idempotent NO-OP on the live table: `waitlist` was a Supabase-dashboard live edit (CTO audit finding B3) with no migration; this brings it under version control so it is reproducible in a fresh environment. RLS is ON with ONLY anon-INSERT (no select/update/delete policy), so the list is write-only for public sign-ups. Tightening the leftover dashboard-era anon/authenticated grants down to insert-only is a DEFERRED follow-up (`00NN_waitlist_revoke.sql`), deliberately not done here. The live form posts to Google Sheets (SheetMonkey) today; this table is the schema-of-record for a future Supabase-backed waitlist. |

## Applying migrations

Production is applied via a direct Postgres connection (`DATABASE_URL` + asyncpg,
the same path the seed loader uses), run locally by the owner (see `Docs/Deploy.md`).
The Supabase CLI below is an equivalent way to apply the migration files to a
linked remote or a local stack. Install the CLI (`brew install supabase/tap/supabase`
or see the Supabase docs), then from the `tiwani-api/` repo root:

1. **Link the repo to the Supabase project** (one time, uses the project ref
   from the Supabase dashboard URL):

   ```sh
   supabase link --project-ref <your-project-ref>
   ```

2. **Apply the migrations.** Push the local migration files to the linked remote
   database:

   ```sh
   supabase db push
   ```

   For a **local** Supabase stack instead (Docker), run the stack and apply the
   pending migrations to it:

   ```sh
   supabase start
   supabase migration up
   ```

3. **Verify** the tables, the RLS policies, and the `child_profile(user_id)`
   index exist, then run the RLS baseline check: signed in as user A, a read of
   user B's rows must return nothing (RLS fails closed).

## Conventions for new migrations

- Numbered and ordered: `0002_*.sql`, `0003_*.sql`, and so on. The number is the
  apply order.
- Every table **enables RLS** and ships **explicit per-operation policies**
  (no `FOR ALL`) keyed to `auth.uid()`. A table without an RLS policy is a
  data-leak path and is not Done.
- Structured codes (not free text) for anything the engine or the LCI reads;
  use checks, foreign keys, and constraints to keep values valid.
- Schema changes are migrations only: no `create_all`, no live table edits, no
  second schema source.
