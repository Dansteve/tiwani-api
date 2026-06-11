"""No-DB tests for the v3 pydantic schemas (app/models/user_profile, child_profile).

These exercise the api contract shapes and the structured-code validation only.
They touch no database: pydantic validation is pure. They pin that the schemas
match the columns in supabase/migrations/0001_foundation.sql and that the
support-level and tag vocabularies (from SeedData.md) are enforced.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.child_profile import (
    ChildProfile,
    ChildProfileCreate,
    ChildProfileUpdate,
    SupportLevelCode,
    Tag,
)
from app.models.user_profile import (
    SubscriptionTier,
    UserProfile,
    UserProfileCreate,
    UserProfileUpdate,
)

# ---------------------------------------------------------------------------
# user_profile
# ---------------------------------------------------------------------------


def test_user_profile_create_requires_first_name():
    # first_name is required (used to greet the Coordinator, Auth.md).
    with pytest.raises(ValidationError):
        UserProfileCreate(id="u-1", email="a@example.com")


def test_user_profile_create_defaults_match_migration():
    profile = UserProfileCreate(id="u-1", email="a@example.com", first_name="Ada")
    # Defaults mirror the table: subscription_tier 'free', onboarding_complete false.
    assert profile.subscription_tier == SubscriptionTier.FREE
    assert profile.subscription_tier.value == "free"
    assert profile.onboarding_complete is False


def test_user_profile_rejects_unknown_subscription_tier():
    with pytest.raises(ValidationError):
        UserProfileCreate(
            id="u-1", email="a@example.com", first_name="Ada", subscription_tier="enterprise"
        )


def test_user_profile_update_is_all_optional():
    # A partial update with no fields is valid (nothing changes).
    assert UserProfileUpdate().model_dump(exclude_unset=True) == {}
    assert UserProfileUpdate(onboarding_complete=True).onboarding_complete is True


def test_user_profile_full_shape_round_trips():
    now = datetime.now(timezone.utc)
    profile = UserProfile(
        id="u-1",
        email="a@example.com",
        first_name="Ada",
        subscription_tier=SubscriptionTier.PREMIUM,
        onboarding_complete=True,
        created_at=now,
        updated_at=now,
    )
    dumped = profile.model_dump()
    assert dumped["id"] == "u-1"
    assert dumped["subscription_tier"] == SubscriptionTier.PREMIUM
    assert {"id", "email", "first_name", "subscription_tier", "onboarding_complete",
            "created_at", "updated_at"} == set(dumped.keys())


# ---------------------------------------------------------------------------
# child_profile (general care recipient, D8)
# ---------------------------------------------------------------------------


def test_support_level_codes_are_exactly_the_three():
    # Drives the LCE multiplier; the migration check constraint allows only these.
    assert {c.value for c in SupportLevelCode} == {"SL-LOW", "SL-MED", "SL-HIGH"}


def test_child_profile_create_does_not_accept_user_id():
    # user_id comes from the authenticated session server-side, not the client,
    # and is excluded from the create payload model.
    assert "user_id" not in ChildProfileCreate.model_fields


def test_child_profile_accepts_valid_support_level_and_tags():
    profile = ChildProfileCreate(
        name="Sam",
        age_band="6-8",
        support_level_code="SL-MED",
        tags=["SN-NOISE", "TR-CHANGE", "CM-MIXED", "RC-VAR"],
    )
    assert profile.support_level_code == SupportLevelCode.MED
    assert Tag.SN_NOISE in profile.tags
    assert len(profile.tags) == 4


def test_child_profile_rejects_unknown_support_level():
    with pytest.raises(ValidationError):
        ChildProfileCreate(name="Sam", support_level_code="SL-EXTREME")


def test_child_profile_rejects_unknown_tag_code():
    with pytest.raises(ValidationError):
        ChildProfileCreate(name="Sam", tags=["SN-NOISE", "XX-BOGUS"])


def test_child_profile_defaults_to_empty_tags():
    profile = ChildProfileCreate(name="Sam")
    assert profile.tags == []
    assert profile.support_level_code is None


def test_tag_vocabulary_covers_the_four_families():
    codes = {t.value for t in Tag}
    # Spot-check one representative code per family is present (SeedData.md taxonomy).
    assert {"SN-NOISE", "TR-CHANGE", "CM-MIXED", "RC-VAR"}.issubset(codes)
    # Counts per SeedData.md: SN 9, TR 6, CM 7, RC 4 => 26 total.
    assert sum(c.startswith("SN-") for c in codes) == 9
    assert sum(c.startswith("TR-") for c in codes) == 6
    assert sum(c.startswith("CM-") for c in codes) == 7
    assert sum(c.startswith("RC-") for c in codes) == 4
    assert len(codes) == 26


def test_child_profile_update_is_all_optional():
    assert ChildProfileUpdate().model_dump(exclude_unset=True) == {}


def test_child_profile_rejects_two_communication_tags():
    # Communication is single-select (SeedData.md): at most one CM- tag on create.
    with pytest.raises(ValidationError):
        ChildProfileCreate(name="Sam", tags=["CM-MIXED", "CM-VERBAL"])


def test_child_profile_rejects_two_recovery_tags():
    # Recovery is single-select: at most one RC- tag.
    with pytest.raises(ValidationError):
        ChildProfileCreate(name="Sam", tags=["RC-SHORT", "RC-EXT"])


def test_child_profile_allows_many_sensory_and_transition_tags():
    # Sensory and Transitions are multi-select; the combined 10-cap is UI-only,
    # so the model accepts several of them plus one CM and one RC.
    profile = ChildProfileCreate(
        name="Sam",
        tags=["SN-NOISE", "SN-CROWD", "SN-LIGHT", "TR-CHANGE", "TR-WAIT", "CM-MIXED", "RC-VAR"],
    )
    assert len(profile.tags) == 7


def test_child_profile_update_rejects_single_select_violation():
    with pytest.raises(ValidationError):
        ChildProfileUpdate(tags=["CM-MIXED", "CM-AAC"])


def test_child_profile_full_shape_includes_user_id():
    now = datetime.now(timezone.utc)
    profile = ChildProfile(
        id="c-1",
        user_id="u-1",
        name="Sam",
        age_band="6-8",
        support_level_code=SupportLevelCode.HIGH,
        tags=[Tag.SN_NOISE],
        created_at=now,
        updated_at=now,
    )
    assert profile.user_id == "u-1"
    assert profile.support_level_code == SupportLevelCode.HIGH
