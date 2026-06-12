# Tiwani API

The brain of TIWANI, a Life Continuity Platform for the family members and carers who manage daily life for someone with additional needs. This service owns authentication, all data, and the three authoritative engines. The app and the website are clients; no scoring or index math ever happens outside this repo.

## What it does

This is a Python + FastAPI service on Supabase. It owns:

- The **Life Continuity Engine (LCE, Product.md section 4.4)**: a deterministic, rules-based, server-side scorer. It looks up base scores from the seeded scenario matrix, applies the support-level multiplier and the permanent tag and "today" flag modifiers, caps each dimension at 5, totals 4 to 20, maps to a participation tier, and ranks strategies. Same inputs always produce the same output. No AI, no randomness.
- The **Life Continuity Index (LCI, Product.md section 4.8)**: a 0 to 100 resilience score per Life Chapter and overall. It starts at 50 on a chapter's first pulse and adjusts cumulatively by a fixed outcome-by-tier table, bounded and rounded after each change.
- The **Erosion Alerts (Product.md section 4.9)**: tier-plus-outcome thresholds evaluated after every pulse, with governed copy that only signposts community and statutory support (psychiatrist sign-off gated).
- **Pulse**: post-activity check-ins that record the outcome and trigger the LCI recompute and alert evaluation.
- **Continuity Cards**: a shareable one-page support summary for a helper, via a 30-day share link with no personal data, plus soft-revoke and a read-time staleness signal.
- **Strategy Library**: auto-save, promotion, suppression, and cross-context surfacing of what works.
- **Shared-Child sharing**: a Coordinator shares a recipient's Continuity Card with another person who sees only that card, with recorded consent, a visible roster, and instant owner-revoke.
- **Village Hub**: a closed need to claim to confirm to done follow-through loop for a Coordinator's village of helpers, with minimum visibility and per-recipient consent gating a broadcast.
- **Subscription and billing**: a database-driven paid-tier entitlement gate, with a Stripe-signature webhook as the only writer of subscription state.

The authoritative engines (sections 4.4, 4.8, 4.9) are built to the spec exactly, with the stated rounding, caps, ordering, and boundaries, and are pinned by table-driven tests against the worked numbers in `Product.md`.

## Stack

- **Python + FastAPI** (ASGI, run under uvicorn), Pydantic v2 for request/response schemas and settings.
- **Supabase** as the stack of record: managed Postgres plus Supabase Auth (email and Google). There is one auth path; the service does not issue or validate its own JWTs.
- Deploys to **Render** (the repo root `Dockerfile` plus `render.yaml` blueprint); the runtime talks to Supabase over HTTP.

## Multi-tenant isolation

TIWANI launches publicly and holds data about real, vulnerable people and their families, so isolation is a security boundary, not a convenience filter. Every read is scoped to the authenticated user. The first line is server-side scoping (the user is resolved from the Supabase session and every query is filtered by `user_id`); the backstop is **Supabase Row Level Security** on every table, so a query physically cannot return another user's rows. A care recipient (`child_id`) is intra-user, threaded through the reads so a Coordinator with several recipients sees only the one selected.

## API surface

All resource routes are mounted under `/api/v1` behind the Supabase-Auth current-user dependency. The current routers are: profile and onboarding, dashboard chapters, preparation plans (LCE), pulses, the Life Continuity Index, Erosion Alerts, Continuity Cards, account (data export and soft delete), the Strategy Library, Shared-Child sharing, the Village Hub, and subscription and billing.

A small number of routes are unauthenticated by design: the health check, the Continuity Card token read (the helper has no account; served through a `SECURITY DEFINER` function), and the Stripe webhook (authenticated by Stripe signature, not a Supabase session).

- Swagger UI: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`
- OpenAPI JSON: `http://localhost:8000/api/openapi.json`
- Health check: `GET /` and `GET /health`

## Database and migrations

The schema, including every Row Level Security policy, is owned by SQL migrations under `supabase/migrations/`, never by ad-hoc table creation. The v3 tables include `user_profile`, `child_profile`, `activity_record`, `pulse_record`, `lci_snapshot`, `alert_record`, `card_record`, `strategy_library_item`, the sharing and village tables (`recipient_membership`, `recipient_invite`, `share_consent`, `recipient_village_consent`, `village_need`, `village_need_event`), and the subscription tables (`plan_tier`, `feature_entitlement`, `subscription`, `billing_event`). The LCE reads its scores from the seeded reference tables (`scenario_matrix`, `scenario_strategy`, `tag_modifier`), never hardcoded values. A migration is applied to the database, and any seed or reference table populated, in the same change. See `supabase/README.md` for the apply and seed procedure.

## Setup

1. Create and activate a Python virtual environment:

```bash
cd tiwani-api
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy the environment example and fill in the values:

```bash
cp .env.example .env
```

Set these variables in `.env` (no secrets are committed to the repo):

- `HOST`, `PORT`, `DEBUG` (FastAPI runtime)
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (Supabase project)
- `DATABASE_URL` (the direct Postgres connection string, used only for local migrations and seeding, not at runtime)
- `CORS_ALLOW_ORIGINS` (a comma-separated allowlist of the app and website origins, never `*`)

## Run

```bash
./start.sh
```

This activates the virtual environment and serves the app under uvicorn on port 8000. Open the Swagger UI at `http://localhost:8000/api/docs`. (The Render container binds the injected `$PORT` instead.)

## Tests

Tests live in `tests/` under **pytest**:

```bash
./venv/bin/python -m pytest -q
```

The engines are pure functions of their inputs and get exhaustive, table-driven tests that assert exact outputs against the worked numbers in `Product.md`: every LCE tier boundary, each support multiplier, the cap-at-5 behaviour, the full LCI outcome-by-tier table, each alert threshold, and a guard test that the prohibited clinical words never appear in emitted copy. User scoping and RLS isolation are tested so one user cannot read another user's rows.

## Governance

The architecture, the cross-cutting patterns, the api hard rules, and the routing table to the per-module docs live in `governance/HardRules/Api/SETUP.md`. The product is defined by `governance/Docs/Product.md` (the PRD); sections 4.4, 4.8, and 4.9 are authoritative and must be built to the number.
