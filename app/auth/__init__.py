"""Auth package: Supabase Auth integration and the current-user dependency.

Supabase Auth owns identity (email + Google); this package wires it into FastAPI
and exposes the current-user dependency that every data route depends on. There
is no second auth path and no hand-rolled JWT (HardRules/Api/Modules/Auth.md).

Public surface: get_current_user (the FastAPI dependency, which also rejects a
closed/soft-deleted account with 410), get_current_user_allow_deleted (pure
authentication with NO closure block, for the self-service /me/export and
/me/delete routes), and AuthedUser (the resolved-user type). Routes import these
from app.auth.
"""

from app.auth.dependencies import (
    AuthedUser,
    get_current_user,
    get_current_user_allow_deleted,
)

__all__ = ["AuthedUser", "get_current_user", "get_current_user_allow_deleted"]
