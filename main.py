import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.routes import (
    profile, chapters, plans, pulses, lci, alerts, cards, account,
    strategies, sharing, village, billing,
)

logger = logging.getLogger(__name__)

# The single governed fallback for a truly-unexpected, otherwise-uncaught error. Calm,
# non-clinical, no internals (Product.md section 4.9 posture): the client never sees the
# exception text or a traceback, only this. The real exception is logged server-side.
# FLAG: this is a user-facing string; it may want copy review.
GENERIC_ERROR_DETAIL = "Something went wrong on our end. Please try again."

# NOTE: debug is deliberately NOT set from settings.DEBUG. FastAPI's debug flag makes
# Starlette's ServerErrorMiddleware render an interactive traceback on an unhandled 500
# (bypassing the governed handler below), which would leak internals to the client even in
# dev. Leaving it False keeps that middleware routing every unhandled 500 to the governed
# handler in all environments. The dev autoreload still uses settings.DEBUG (see uvicorn.run
# at the bottom); the two are independent.
app = FastAPI(
    title=settings.APP_NAME,
    description="FastAPI Backend for Tiwani App, integrated with Supabase",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Set up CORS middleware to allow the frontend to interact with the API.
# Origins come from config (CORS_ALLOW_ORIGINS), an explicit allowlist, never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global catch-all for an UNHANDLED exception at the app boundary. FastAPI's own handlers
# already shape the typed 4xx paths the routes raise (HTTPException -> {"detail": ...},
# RequestValidationError -> 422); this handler is NOT registered for those, so it does not
# change any existing 4xx response. It fires ONLY for a truly-unexpected error that no route
# caught (an uncaught Supabase APIError, the village _rpc unknown-SQLSTATE re-raise, any bug),
# turning what would otherwise be a raw 500 (a leaked traceback) into a clean governed
# response: the same {"detail": ...} body shape the routes use, a fixed non-clinical message,
# and NO exception text, traceback, or internals. The real exception is logged server-side
# (logger.exception captures the traceback) so debugging is unaffected.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": GENERIC_ERROR_DETAIL},
    )


# v1 surface (clean rebuild, Docs/Decisions.md D2): profile, care recipient,
# onboarding, and the six-chapter dashboard, behind the Supabase-Auth current-user
# dependency. The pre-v3 prototype routers (auth/user/children/chapters) are
# un-mounted (CTO audit B1): they queried unmanaged tables through a no-token anon
# client that RLS did not scope, so only the RLS-scoped v1 surface is mounted.
app.include_router(profile.router, prefix="/api/v1", tags=["v1 Profile & Onboarding"])
app.include_router(chapters.router, prefix="/api/v1", tags=["v1 Dashboard Chapters"])
# The Life Continuity Engine endpoints (Product.md section 4.4): prepare a plan and
# the activity picker. Registered under /api/v1 behind the current-user dependency.
app.include_router(plans.router, prefix="/api/v1", tags=["v1 Preparation Plan (LCE)"])
# The Pulse (section 4.7): record a post-activity outcome (which recomputes the LCI)
# and list the pending check-ins. Registered under /api/v1 behind current-user.
app.include_router(pulses.router, prefix="/api/v1", tags=["v1 Pulse (post-activity)"])
# The Life Continuity Index (section 4.8): the overall and per-chapter resilience
# scores the dashboard reads. Registered under /api/v1 behind current-user.
app.include_router(lci.router, prefix="/api/v1", tags=["v1 Life Continuity Index"])
# The Erosion Alerts (section 4.9, GOVERNED copy, psychiatrist sign-off gated, Task
# 12): list the active alerts and dismiss one. Evaluated server-side after every
# pulse. Registered under /api/v1 behind current-user.
app.include_router(alerts.router, prefix="/api/v1", tags=["v1 Erosion Alerts"])
# The Continuity Card (section 4.6): generate a shareable one-page support summary for
# a helper (POST, auth) and read one by its share token (GET, NO auth, the helper has
# no account). Registered under /api/v1; the token read is the only unauthenticated
# route and is narrow by design (migration 0007 SECURITY DEFINER function).
app.include_router(cards.router, prefix="/api/v1", tags=["v1 Continuity Card"])
# Self-service account (data rights): export the caller's own data as a downloadable
# JSON document, and CLOSE the account (a SOFT delete that sets user_profile.deleted_at;
# the data is retained per the retention policy). Both routes are RLS-scoped to the caller
# and use the allow-deleted authenticator so they work around the moment of closure; every
# OTHER v1 route rejects a closed account with 410 (the soft-delete block in
# get_current_user). Registered under /api/v1 behind the current-user dependency.
app.include_router(account.router, prefix="/api/v1", tags=["v1 Account (export & delete)"])
# The Strategy Library (section 4.10, Task 9): the learning-layer mutations the Coordinator
# drives on a saved strategy: suppress (remove; suppressed after 3 for the scenario), re-allow
# a suppressed one, and dismiss a cross-context "Also worked in [chapter]" surfacing per chapter.
# Auto-save + promotion + the outcome counts happen in the plan/pulse flows; these routes are the
# explicit actions. Registered under /api/v1 behind current-user (normal, not allow-deleted).
app.include_router(strategies.router, prefix="/api/v1", tags=["v1 Strategy Library"])
# Shared-Child sharing (Docs/FeatureDecisions.md, the Shared-Child REFINE entry): a
# Coordinator shares a recipient's Continuity Card with another person, who sees ONLY that
# card (the visibility CEILING), with first-class recorded consent, a visible roster, and
# instant owner-revoke. Built on the 0015 membership substrate + the 0016 feature functions
# (PENDING OWNER APPLY); the user-facing copy is GOVERNED (app/engines/sharing). Writes are
# owner-only at the DB and the service; the card read is membership-gated in SQL. Registered
# under /api/v1 behind the current-user dependency.
app.include_router(sharing.router, prefix="/api/v1", tags=["v1 Shared-Child Sharing"])
# The Village Delegation Hub (Docs/FeatureDecisions.md): a closed need -> claim -> confirm
# -> done / dropped follow-through loop for a Coordinator's village of helpers, riding the
# recipient_membership substrate (migration 0015). A need belongs to ONE recipient; a member
# sees the need + logistics only (MINIMUM VISIBILITY), the exact where/contact is per-claim,
# claims are atomic first-wins, and per-recipient consent gates a broadcast (Art. 9). All
# routes require auth and are RLS-scoped; the schema + RPCs are migration 0017 (PENDING
# OWNER APPLY). The user-facing copy is GOVERNED (psychiatrist sign-off, Task 12).
app.include_router(village.router, prefix="/api/v1", tags=["v1 Village Hub"])
# Subscription + billing (Docs/FeatureDecisions.md, the Subscription DEFER entry): the price
# list and the caller's own subscription (auth, RLS-scoped reads), a STUBBED checkout, and the
# Stripe webhook. The webhook is the ONLY writer of subscription state and authenticates by
# STRIPE SIGNATURE (not a Supabase session), writing through the SECURITY DEFINER RPC
# (migration 0018, PENDING OWNER APPLY) idempotently on the Stripe event id. The live Stripe
# SDK calls are STUBBED (PENDING OWNER STRIPE KEYS); the entitlement gate
# (app/services/entitlements.py) is the one server-side allowlist gate for paid features.
app.include_router(billing.router, prefix="/api/v1", tags=["v1 Subscription & Billing"])

# Health check: the root "/" and "/health" are the same endpoint (Render's health
# check and any uptime pinger can hit either). Returns 200 with a small status body.
@app.get("/")
@app.get("/health")
async def health():
    return {
        "message": "Welcome to the Tiwani API",
        "status": "healthy",
        "version": "1.0.0",
        "docs_url": app.docs_url,
        "redoc_url": app.redoc_url,
        "openapi_url": app.openapi_url
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
