"""user_profile pydantic schemas (v3).

The api contract for the authenticated user's profile, mirroring the
public.user_profile table in supabase/migrations/0001_foundation.sql and the
object in Product.md section 5 / HardRules/Api/Modules/Models.md.

One row per Supabase Auth user (id == auth.users.id). first_name is required
(used to greet the Coordinator); routing after sign-up goes to onboarding, so
onboarding_complete starts false. These are pydantic v2 schemas only: the table
and its RLS policies live in the migration, the single source of schema truth.

SELF-GRANT FIX (Docs/FeatureDecisions.md, Subscription precondition 2). The
subscription tier is SERVER-OWNED, not a field a client may set: it is read-only
on the response (UserProfile) and is NOT a field of the writable surface
(UserProfileUpdate has no subscription_tier; UserProfileBase, the create/echo
shape, no longer carries it). A user can therefore not PUT /api/v3/profile
{"subscription_tier": "premium"} to self-promote: there is no writable field to
set, and the table has no user write policy on the column (the only writer is the
billing webhook through the SECURITY DEFINER RPC apply_subscription_event,
migration 0014). The DB column keeps its 'free' default, so a new profile is free
until the webhook says otherwise.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SubscriptionTier(str, Enum):
    """The subscription tiers (Product.md section 5 + Docs/FeatureDecisions.md).

    Three tiers, free first: 'free' is the default for a new profile (the full
    safety net plus two care recipients, the board red-line), 'standard' and
    'premium' are the paid tiers. The tier KEY is the join key into plan_tier and
    feature_entitlement (migration 0014); the human names and prices live in the
    plan_tier DATA, not here, so a price or name change is a data edit, no redeploy.
    """

    FREE = "free"
    STANDARD = "standard"
    PREMIUM = "premium"


class UserProfileBase(BaseModel):
    """Fields a client may set on a profile.

    Deliberately does NOT include subscription_tier: the tier is server-owned
    (set only by the billing webhook), so it is never part of a client-writable or
    client-created shape. It appears only on the read-only UserProfile response.
    """

    email: Optional[EmailStr] = None
    first_name: str = Field(..., min_length=1)
    onboarding_complete: bool = False


class UserProfileCreate(UserProfileBase):
    """Payload to create a profile (server-side, at sign-up).

    id is the Supabase Auth user id; it is supplied by the resolved session, not
    by an arbitrary client, so the create path is service-role and scoped. No
    subscription_tier: a new profile is always free (the DB column default), never
    a tier the sign-up caller chose.
    """

    id: str


class UserProfileUpdate(BaseModel):
    """Partial update. Every field optional; id and timestamps are not editable.

    subscription_tier is intentionally ABSENT (the self-grant fix, precondition 2):
    a Coordinator may edit their name and onboarding flag, never their own tier.
    The PUT /api/v3/profile route builds the update from this model's set fields, so
    a client that sends subscription_tier has it dropped (an unknown field is ignored
    by the default model config), and even a forged direct write is refused by RLS
    (no user write policy on the tier column).
    """

    first_name: Optional[str] = Field(default=None, min_length=1)
    onboarding_complete: Optional[bool] = None


class UserProfile(UserProfileBase):
    """The full profile as returned by the api (mirrors the table row).

    Carries the read-only subscription_tier so the app can see the caller's tier
    (to show the plan and decide which paid affordances to surface), even though no
    client may set it. The value comes from the DB row; the authoritative gate is
    always the server-side require_entitlement check (app/services/entitlements.py),
    never the client trusting this field.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    created_at: datetime
    updated_at: datetime
