# Routes package. The v3 routers (profile_v3, chapters_v3, plans, pulses, lci,
# alerts, cards) are imported directly by main.py. This package init intentionally
# imports nothing: the pre-v3 prototype routers (auth/user/children/chapters) were
# removed (CTO audit B1), so app.database / DATABASE_URL is no longer an import-time
# dependency and the service starts on Render without a DATABASE_URL set.
