"""user_profile pydantic schemas (v3).

The api contract for the authenticated user's profile, mirroring the
public.user_profile table in supabase/migrations/0001_foundation.sql and the
object in Product.md section 5 / HardRules/Api/Modules/Models.md.

One row per Supabase Auth user (id == auth.users.id). first_name is required
(used to greet the Coordinator); routing after sign-up goes to onboarding, so
onboarding_complete starts false. These are pydantic v2 schemas only: the table
and its RLS policies live in the migration, the single source of schema truth.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SubscriptionTier(str, Enum):
    """Subscription tiers. 'free' is the default for a new profile."""

    FREE = "free"
    PREMIUM = "premium"


class UserProfileBase(BaseModel):
    """Fields a client may set on a profile."""

    email: Optional[EmailStr] = None
    first_name: str = Field(..., min_length=1)
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    onboarding_complete: bool = False


class UserProfileCreate(UserProfileBase):
    """Payload to create a profile (server-side, at sign-up).

    id is the Supabase Auth user id; it is supplied by the resolved session, not
    by an arbitrary client, so the create path is service-role and scoped.
    """

    id: str


class UserProfileUpdate(BaseModel):
    """Partial update. Every field optional; id and timestamps are not editable."""

    first_name: Optional[str] = Field(default=None, min_length=1)
    subscription_tier: Optional[SubscriptionTier] = None
    onboarding_complete: Optional[bool] = None


class UserProfile(UserProfileBase):
    """The full profile as returned by the api (mirrors the table row)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
