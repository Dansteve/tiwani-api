"""Onboarding payload schema (v3).

The structured payload the app posts ONCE at the end of the three-screen
onboarding (Product.md section 4.2, HardRules/App/Modules/Onboarding.md). The app
collects coded values across the three screens (about your child, what they find
challenging, first activity) and submits them in a single write; the api creates
or updates the care recipient and marks the user_profile onboarding_complete.

This reuses the SupportLevelCode and Tag vocabularies from
app/models/child_profile.py (no second vocabulary) so the codes the engine reads
are defined in exactly one place.

Scope boundary: the "first activity" (chapter + activity selection from screen 3)
is captured here as structured identifiers so the app can route the Coordinator
into their first plan, but it is NOT scored or persisted as an activity_record by
this endpoint. The LCE (Product.md section 4.4) and the activity_record table are
Task 5 and are blocked on the seed companion docs (Q7, SeedData.md). This endpoint
owns the profile + onboarding-complete data only; it does not run the engine.

The single-select rule for Communication and Recovery (SeedData.md: those two
families are single-select) is a data-shape rule and is validated here. The
"max 10 across Sensory + Transitions combined" cap is UI-only per SeedData.md
(the database stores every selected tag), so it is not enforced server-side.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.child_profile import SupportLevelCode, Tag, validate_single_select_tags


class OnboardingActivitySelection(BaseModel):
    """Screen 3: the first chapter + activity the Coordinator chooses to prepare.

    Captured as structured identifiers for routing into the first plan. Not
    scored here (the LCE is Task 5). chapter and activity are opaque structured
    strings at this stage because the chapter set and the activity scenario
    matrix are seed-blocked (Q7); they are stored on the payload, not validated
    against a seeded vocabulary that does not exist yet, and are not written to
    an activity_record by this endpoint.
    """

    chapter: str = Field(..., min_length=1)
    activity: str = Field(..., min_length=1)


class OnboardingPayload(BaseModel):
    """The full onboarding submission, posted once at the end.

    Mirrors the three screens: the care recipient's name / age band / support
    level (screen 1), the challenge tags (screen 2), and the first activity
    selection (screen 3). All scoring inputs are structured codes.
    """

    # Screen 1: about your child (the care recipient).
    name: str = Field(..., min_length=1)
    age_band: Optional[str] = None
    support_level_code: SupportLevelCode

    # Screen 2: what they find challenging (coded tags).
    tags: List[Tag] = Field(default_factory=list)

    # Screen 3: first activity to prepare for (for routing, not scored here).
    first_activity: Optional[OnboardingActivitySelection] = None

    @field_validator("tags")
    @classmethod
    def _single_select_families(cls, tags: List[Tag]) -> List[Tag]:
        # The single-select rule (CM-/RC-) is defined once in child_profile and
        # reused here so every write path enforces it identically.
        return validate_single_select_tags(tags)
