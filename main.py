import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routes import auth, user, children, chapters
from app.routes import profile_v3, chapters_v3, plans, pulses, lci, alerts, cards

app = FastAPI(
    title=settings.APP_NAME,
    description="FastAPI Backend for Tiwani App, integrated with Supabase",
    version="1.0.0",
    debug=settings.DEBUG,
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

# Register routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(user.router, prefix="/api/user", tags=["User Profile"])
app.include_router(children.router, prefix="/api/children", tags=["Children Management"])
app.include_router(chapters.router, prefix="/api/chapters", tags=["Chapters & Triggers"])

# v3 surface (clean rebuild, Docs/Decisions.md D2): profile, care recipient,
# onboarding, and the six-chapter dashboard, behind the Supabase-Auth current-user
# dependency. Registered under /api/v3 alongside the prototype /api/* routes, which
# are replaced in later tasks.
app.include_router(profile_v3.router, prefix="/api/v3", tags=["v3 Profile & Onboarding"])
app.include_router(chapters_v3.router, prefix="/api/v3", tags=["v3 Dashboard Chapters"])
# The Life Continuity Engine endpoints (Product.md section 4.4): prepare a plan and
# the activity picker. Registered under /api/v3 behind the current-user dependency.
app.include_router(plans.router, prefix="/api/v3", tags=["v3 Preparation Plan (LCE)"])
# The Pulse (section 4.7): record a post-activity outcome (which recomputes the LCI)
# and list the pending check-ins. Registered under /api/v3 behind current-user.
app.include_router(pulses.router, prefix="/api/v3", tags=["v3 Pulse (post-activity)"])
# The Life Continuity Index (section 4.8): the overall and per-chapter resilience
# scores the dashboard reads. Registered under /api/v3 behind current-user.
app.include_router(lci.router, prefix="/api/v3", tags=["v3 Life Continuity Index"])
# The Erosion Alerts (section 4.9, GOVERNED copy, psychiatrist sign-off gated, Task
# 12): list the active alerts and dismiss one. Evaluated server-side after every
# pulse. Registered under /api/v3 behind current-user.
app.include_router(alerts.router, prefix="/api/v3", tags=["v3 Erosion Alerts"])
# The Continuity Card (section 4.6): generate a shareable one-page support summary for
# a helper (POST, auth) and read one by its share token (GET, NO auth, the helper has
# no account). Registered under /api/v3; the token read is the only unauthenticated
# route and is narrow by design (migration 0007 SECURITY DEFINER function).
app.include_router(cards.router, prefix="/api/v3", tags=["v3 Continuity Card"])

@app.get("/")
async def root():
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
