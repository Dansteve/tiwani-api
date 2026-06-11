"""No-DB tests for the onboarding payload schema (app/models/onboarding).

Pure pydantic validation; no database. Pins the contract the app mirrors: the
structured codes required at the end of the three-screen onboarding, the reuse of
the child_profile vocabularies, the single-select rule, and that the first
activity is an optional structured selection (carried for routing, not scored).
"""

import pytest
from pydantic import ValidationError

from app.models.child_profile import SupportLevelCode, Tag
from app.models.onboarding import OnboardingActivitySelection, OnboardingPayload


def test_minimal_payload_requires_name_and_support_level():
    payload = OnboardingPayload(name="Sam", support_level_code="SL-MED")
    assert payload.name == "Sam"
    assert payload.support_level_code == SupportLevelCode.MED
    assert payload.tags == []
    assert payload.first_activity is None


def test_payload_requires_support_level():
    # support_level_code is required (it sets the LCE multiplier).
    with pytest.raises(ValidationError):
        OnboardingPayload(name="Sam")


def test_payload_requires_name():
    with pytest.raises(ValidationError):
        OnboardingPayload(support_level_code="SL-LOW")


def test_payload_accepts_full_coded_submission():
    payload = OnboardingPayload(
        name="Sam",
        age_band="6-8",
        support_level_code="SL-HIGH",
        tags=["SN-NOISE", "TR-CHANGE", "CM-MIXED", "RC-VAR"],
        first_activity={"chapter": "mornings", "activity_type": "school-run"},
    )
    assert Tag.SN_NOISE in payload.tags
    assert isinstance(payload.first_activity, OnboardingActivitySelection)
    assert payload.first_activity.chapter == "mornings"
    assert payload.first_activity.activity_type == "school-run"


def test_payload_rejects_unknown_tag():
    with pytest.raises(ValidationError):
        OnboardingPayload(name="Sam", support_level_code="SL-LOW", tags=["XX-BOGUS"])


def test_payload_rejects_two_communication_tags():
    with pytest.raises(ValidationError):
        OnboardingPayload(
            name="Sam", support_level_code="SL-LOW", tags=["CM-MIXED", "CM-VERBAL"]
        )


def test_payload_rejects_two_recovery_tags():
    with pytest.raises(ValidationError):
        OnboardingPayload(
            name="Sam", support_level_code="SL-LOW", tags=["RC-SHORT", "RC-EXT"]
        )


def test_first_activity_requires_chapter_and_activity_type():
    with pytest.raises(ValidationError):
        OnboardingActivitySelection(chapter="mornings")
