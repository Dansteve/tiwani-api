"""v3 profile, care-recipient, and onboarding routes.

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the profile
service, serialize. All routes require the current-user dependency (401 if the
bearer token is missing or invalid); every read and write is user-scoped through
the service, with Supabase RLS as the database backstop. A cross-user access
attempt returns 404 (the row is invisible under RLS), not a confirmation that it
exists.

These are the v3 surface, registered under /api/v3 in main.py, sitting alongside
the prototype /api/* routes (replaced in later tasks). They use the new
app/auth dependency and the app/services/profile data layer, not the prototype's
inline-Supabase routes.

Endpoints:
  GET  /api/v3/profile     the caller's user_profile (created on first access)
  PUT  /api/v3/profile     update the caller's profile (partial)
  POST /api/v3/child       create the caller's care recipient
  GET  /api/v3/child       the caller's active care recipient (404 if none)
  GET  /api/v3/children    the caller's care recipients (the switcher list)
  PUT  /api/v3/child/{id}  update the caller's care recipient (partial)
  POST /api/v3/onboarding  the structured onboarding write (once); marks complete
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthedUser, get_current_user
from app.models.child_profile import (
    ChildProfile,
    ChildProfileCreate,
    ChildProfileUpdate,
)
from app.models.onboarding import OnboardingPayload
from app.models.user_profile import UserProfile, UserProfileUpdate
from app.services import profile as profile_service

router = APIRouter()


# ---------------------------------------------------------------------------
# user_profile
# ---------------------------------------------------------------------------


@router.get("/profile", response_model=UserProfile)
def get_profile(user: AuthedUser = Depends(get_current_user)) -> UserProfile:
    """Return the caller's profile, creating the row on first access.

    The app signs the user up via the Supabase Auth SDK, so the api can see an
    authenticated user before a profile row exists; the service creates it
    (service-role, scoped to the caller's id) on first read.
    """
    row = profile_service.get_or_create_profile(user)
    return UserProfile.model_validate(row)


@router.put("/profile", response_model=UserProfile)
def update_profile(
    update: UserProfileUpdate,
    user: AuthedUser = Depends(get_current_user),
) -> UserProfile:
    """Update the caller's profile (partial). 400 if no fields were supplied."""
    fields = update.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update fields provided",
        )
    row = profile_service.update_profile(user, fields)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return UserProfile.model_validate(row)


# ---------------------------------------------------------------------------
# child_profile (general care recipient, D8)
# ---------------------------------------------------------------------------


@router.post("/child", response_model=ChildProfile, status_code=status.HTTP_201_CREATED)
def create_child(
    payload: ChildProfileCreate,
    user: AuthedUser = Depends(get_current_user),
) -> ChildProfile:
    """Create the caller's care recipient.

    user_id is taken from the session, never the client; the RLS insert policy
    requires user_id == auth.uid(), so the row can only belong to the caller.

    Interim one-recipient guard (Docs/FeatureDecisions.md, step 1): a SECOND
    create is rejected with 409 (the service raises CareRecipientExistsError);
    the first create, onboarding, and the update path are unaffected.
    """
    try:
        row = profile_service.create_child(user, payload.model_dump())
    except profile_service.CareRecipientExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only one care recipient is supported right now. "
                "Managing more than one is coming soon."
            ),
        ) from exc
    return ChildProfile.model_validate(row)


@router.get("/child", response_model=ChildProfile)
def get_child(user: AuthedUser = Depends(get_current_user)) -> ChildProfile:
    """Return the caller's active care recipient; 404 if none exists yet."""
    row = profile_service.get_child(user)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No care recipient found",
        )
    return ChildProfile.model_validate(row)


@router.get("/children", response_model=List[ChildProfile])
def list_children(user: AuthedUser = Depends(get_current_user)) -> List[ChildProfile]:
    """Return the caller's care recipients, newest first (the future switcher list).

    The list the app's recipient switcher reads to pick the active child_id for the
    per-recipient dashboard / LCI / alerts. RLS-scoped to the caller, so it can only
    ever return the caller's own recipients. Empty for a fresh user with no recipient
    yet; today the one-recipient guard means it is a single element, and it is already
    correct for several recipients once the guard is lifted. Unlike GET /child, an empty
    list is a 200 (not a 404): "you have no recipients" is a valid switcher state.
    """
    rows = profile_service.list_children(user)
    return [ChildProfile.model_validate(row) for row in rows]


@router.put("/child/{child_id}", response_model=ChildProfile)
def update_child(
    child_id: str,
    update: ChildProfileUpdate,
    user: AuthedUser = Depends(get_current_user),
) -> ChildProfile:
    """Update the caller's care recipient (partial).

    400 if no fields were supplied. 404 if the id is not a row the caller owns
    (RLS scopes the update to the caller, so a forged id matches nothing). Edits
    apply to plans only; historical records never change (section 4.11).
    """
    fields = update.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update fields provided",
        )
    row = profile_service.update_child(user, child_id, fields)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Care recipient not found",
        )
    return ChildProfile.model_validate(row)


# ---------------------------------------------------------------------------
# onboarding write
# ---------------------------------------------------------------------------


class OnboardingResult(UserProfile):
    """Onboarding response is the updated profile plus the care recipient row."""

    # Inherit the full user_profile shape, then attach the recipient.
    child: ChildProfile


@router.post("/onboarding", response_model=OnboardingResult)
def complete_onboarding(
    payload: OnboardingPayload,
    user: AuthedUser = Depends(get_current_user),
) -> OnboardingResult:
    """Accept the structured onboarding payload once; mark onboarding complete.

    Creates or updates the care recipient (one active per user for the MVP) and
    sets onboarding_complete = true, in one call. The first_activity selection is
    carried for the app's routing into the first plan but is NOT scored or
    persisted as an activity_record here (the LCE is Task 5). Returns the updated
    profile plus the recipient.
    """
    result = profile_service.complete_onboarding(user, payload.model_dump())
    profile_row = dict(result["profile"])
    profile_row["child"] = result["child"]
    return OnboardingResult.model_validate(profile_row)
