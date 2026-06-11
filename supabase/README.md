# Supabase schema and migrations

This directory is the **single source of schema truth** for `tiwani-api`: the
Postgres tables, their Row Level Security (RLS) policies, and any seed SQL, all
expressed as ordered migrations. No table is created by `create_all` and no
table is edited live in the Supabase dashboard; every column and policy lands
here as a migration, applied and recorded (`HardRules/Api/Modules/Models.md`,
`HardRules/Api/SETUP.md`).

## Status: NOT YET APPLIED

The migrations here are **reviewable SQL that has not been applied to any
database**. There is no Supabase dev project, no local Postgres, and no Docker
in the current environment, so the SQL was written and self-reviewed but not
run. Applying it (and verifying the RLS baseline: a second user cannot read the
first user's rows) is blocked on a Supabase dev project with rotated
credentials, tracked in `Tasks/1.FoundationsAndSafetyNet.md`.

## How these relate to the prototype tables

These migrations are **additive**. The prototype currently uses tables named
`profiles`, `children`, `chapters`, and `triggers` (a pre-v3 "chapters +
triggers + status" model). The v3 migrations here create **new** tables
(`user_profile`, `child_profile`, and more in later migrations) **alongside**
those prototype tables. They do not drop or alter the prototype tables. The
prototype tables are replaced in later rebuild tasks (`Docs/Decisions.md` D2,
the clean rebuild to PRD v3); once the v3 model is in use and the old data is
handled, a later migration removes them.

## Migrations

| File | Adds | Notes |
| --- | --- | --- |
| `migrations/0001_foundation.sql` | `user_profile`, `child_profile` (the two stable v3 foundation tables), an index on `child_profile(user_id)`, a shared `set_updated_at()` trigger, and the RLS policies for both | `child_profile` is modelled as a general care recipient per `Docs/Decisions.md` D8 (the name is kept for the MVP). Both tables have RLS enabled with explicit per-operation policies keyed to `auth.uid()`. |
| `migrations/0002_seed_knowledge_base.sql` | The LCE seed reference tables `scenario_matrix`, `scenario_strategy`, `tag_modifier` (the scenario base scores + ranked strategies + per-tag dimension modifiers the engine reads), with CHECK constraints incl. the `temporal+sensory+logistical+human = stated_total` transcription guard | GLOBAL reference data, not user data: RLS enabled but read-for-authenticated, write-for-none (the versioned seed loader writes with the service-role key). Rows are written by `app/seed/write_seed_to_db`. |
| `migrations/0003_activity_record.sql` | `activity_record` (the stored LCE plan: base + final scores, total, tier, today flags, ranked strategies JSON, `scheduled_pulse_at`, optional `context_note`), indexes on `(user_id, chapter)` and `child_id`, a `total = sum of the four cells` check, the shared `set_updated_at` trigger, and RLS policies | USER data: RLS enabled with explicit per-operation policies keyed to `auth.uid()` (same pattern as `child_profile`). Written by `app/services/plans.py` (LCE step 8). |

## Applying with the Supabase CLI (once a dev project exists)

Install the CLI (`brew install supabase/tap/supabase` or see the Supabase
docs), then from the `tiwani-api/` repo root:

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
   index exist, then run the RLS baseline check from
   `Tasks/1.FoundationsAndSafetyNet.md`: signed in as user A, a read of user B's
   rows must return nothing (RLS fails closed).

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
