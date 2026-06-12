# Demo data seed (`seed_demo_data.py`)

Seed a realistic, populated TIWANI account into a **demo / throwaway** Supabase project so
the beta can be demoed against believable data: one Coordinator, two care recipients, and a
six-week, six-chapter history (prepared plans, post-activity pulses with mixed outcomes, a
**natural** Erosion Alert, and a couple of Continuity Cards).

The data is **engine-consistent**: every score, tier, strategy, LCI value, trajectory, and
the alert is produced by the real services and engines (`app/services/*`, `app/engines/*`)
at insert time. Nothing is hand-faked. The script only chooses the inputs a real Coordinator
would have entered (which seeded activity, what pulse outcome, on which day).

## Critical safety (read first)

This script **writes rows**. It is for the **owner** to run against a **demo / throwaway**
project, never production. Two guards enforce that:

1. **The target is explicit.** The connection is read from `DEMO_SUPABASE_URL`,
   `DEMO_SUPABASE_KEY`, `DEMO_SUPABASE_SERVICE_ROLE_KEY` (or the `--url` / `--anon-key` /
   `--service-role-key` flags). It deliberately does **not** read the app's own
   `SUPABASE_*` / `.env`, so a loaded app environment cannot make you seed the live project
   by accident.
2. **The known production host is hard-refused.** The production host is pinned in
   `PRODUCTION_HOSTS` in `seed_demo_data.py`; if the target URL resolves to it, the script
   **aborts before any write** (exit code 2). This mirrors the explicit-target posture of
   the real-Postgres RLS test (`tests/test_rls_isolation.py`), which only ever runs against
   a non-production database. If production ever moves, add the new host to `PRODUCTION_HOSTS`
   (and keep the old one listed).

The target project must already have the migrations applied (`supabase/migrations/`, the v3
tables and their RLS policies) and Auth enabled.

## What it seeds

A single demo Coordinator (`tiwani-demo.coordinator@example.com`, a reserved-domain demo
address, no real PII) with two care recipients:

| Recipient | Support | The story it shows |
| --- | --- | --- |
| **Amara Bello** | `SL-LOW` | A **Family** chapter that **erodes**: a recurring Full-tier bedtime struggle with Difficult outcomes drives the chapter LCI down week over week into the critical band, raising a **natural L3 Erosion Alert** (the section 4.9 LCI-below-30 branch). Calmer School history and one recent **pending** check-in (Travel). |
| **Theo Okafor** | `SL-HIGH` | A **Social** chapter that **strengthens** (Well/Okay on Continuity Pivot activities, a rising LCI, no alert), a **School** chapter that reaches the **natural L1 early signal** (the activity/pulse counts branch), and a **sparse Travel** chapter (one pulse, the "building your picture" state). One Continuity Card each. |

So the demo dashboard shows, side by side: an eroding chapter with an active alert, a
strengthening success chapter, a sparse chapter, a pending check-in, and shared cards. The
exact sequences live in `scripts/demo_data.py` and are verified by `tests/test_demo_seed.py`
(which folds them through the real engines to prove the alert fires naturally).

## How to run

From the **repo root** (`tiwani-api/`):

```bash
# 1. Point at the DEMO project (NOT production):
export DEMO_SUPABASE_URL="https://<your-demo-project-ref>.supabase.co"
export DEMO_SUPABASE_KEY="<demo anon key>"
export DEMO_SUPABASE_SERVICE_ROLE_KEY="<demo service-role key>"

# 2. Dry run first: confirms the target is accepted (not production) and the blueprint
#    composes, and writes NOTHING.
python -m scripts.seed_demo_data --dry-run

# 3. Seed it for real:
python -m scripts.seed_demo_data
```

You can also pass the connection on the command line instead of the environment
(`--url`, `--anon-key`, `--service-role-key`); flags override the env. Run
`python -m scripts.seed_demo_data --help` for the full usage.

After it runs, sign in to the demo app as `tiwani-demo.coordinator@example.com` (the demo
password is printed at the end of the run and set in `scripts/demo_data.py`) to view the
populated account.

## Idempotency

Re-running is safe. The script finds-or-creates the one demo Auth user by its fixed demo
email and, before reseeding, deletes **that user's** prior demo rows (cards, snapshots,
pulses, alerts, activities, care recipients) under that user's own RLS session. It never
touches any other user's data, and it never creates a second demo Coordinator.

## Tests

The insert path is owner-run (there is no disposable database in CI), but the logic is
verified offline by `tests/test_demo_seed.py`:

- the pure timeline helpers (`scripts/demo_data.py`);
- **engine consistency**: the blueprint sequences are folded through the real LCE / LCI /
  alert engines and asserted to produce the tiers, scores, trajectories, and the **natural
  Erosion Alert** the demo claims;
- the **production-refusal** guard (the pinned host is refused; a demo host is accepted; an
  unspecified target fails closed);
- import + compose with no live database.

Run them with:

```bash
python -m pytest tests/test_demo_seed.py
```
