"""Services: the thin data layer between the v3 routes and Supabase.

Routes stay thin (parse, call a service, serialize) per HardRules/Api/SETUP.md.
DOMAIN logic (scoring, the LCI, alerts) lives in app/engines/; these services are
DATA plumbing only: they read and write the v3 profile and care-recipient rows
through the RLS-scoped Supabase client and own no engine logic.

Every read and write here is user-scoped: the caller passes the resolved
AuthedUser, and the service uses get_anon_client(user.access_token) so Row Level
Security filters to that user's rows. The one deliberate service-role use is
creating the user_profile row on first access (the migration has no insert policy
for user_profile by design; the row is keyed to auth.uid() and created
server-side), and it is scoped explicitly to the authenticated user's id.
"""
