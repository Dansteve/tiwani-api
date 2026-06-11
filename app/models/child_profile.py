"""child_profile pydantic schemas (v3), modelled as a general care recipient.

The api contract for a care recipient, mirroring the public.child_profile table
in supabase/migrations/0001_foundation.sql and the object in Product.md
section 5 / HardRules/Api/Modules/Models.md.

D8 (Docs/Decisions.md): TIWANI spans additional-needs caregiving across the
lifespan (child and adult/elder care). This object is named child_profile for
the child-first MVP, but it is modelled as a general care recipient: the columns
do not assume a child, so adult care is not a schema rewrite later. The MVP UI
may still say "child".

The support level and the tags are STRUCTURED CODES, never free text, because
the LCE reads them (HardRules/Api/SETUP.md idea 4): the support_level_code drives
the multiplier and the tags drive the permanent modifiers. The code vocabularies
below come from HardRules/Api/Modules/SeedData.md (the recovered Tag Architecture
v1.0 taxonomy). The per-tag modifier VALUES live in the seed, not here, and are
BLOCKED on the companion docs (Q7); this schema only pins the valid code set.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupportLevelCode(str, Enum):
    """Support level. Drives the LCE multiplier (LOW x1.0, MED x1.2, HIGH x1.4)."""

    LOW = "SL-LOW"
    MED = "SL-MED"
    HIGH = "SL-HIGH"


class Tag(str, Enum):
    """The care-recipient tag vocabulary (Tag Architecture v1.0, SeedData.md).

    Five families. FOUR are PERMANENT profile tags chosen at onboarding and editable
    later: Sensory (SN-, multi-select), Transitions (TR-, multi-select),
    Communication (CM-, single-select), Recovery (RC-, single-select). The fifth,
    Triggers (TG-), are the section 4.4 "today" flags expressed as tags: parent-added,
    day-level "today flags" that temporarily elevate scores for ONE day and never
    change the saved profile (Product.md section 4.4; Tag Architecture v1.0 Part 2
    "Known triggers"). The Sensory + Transitions max-10 cap is UI-only (the table
    stores every selected tag). The per-tag modifier VALUES are seed data
    (app/seed/tag_architecture_v1.py), an exact transcription of Tag Architecture
    v1.0; this enum only pins the valid code set.
    """

    # Sensory (SN-, multi-select)
    SN_NOISE = "SN-NOISE"
    SN_CROWD = "SN-CROWD"
    SN_LIGHT = "SN-LIGHT"
    SN_TEXTURE = "SN-TEXTURE"
    SN_SMELL = "SN-SMELL"
    SN_TASTE = "SN-TASTE"
    SN_TOUCH = "SN-TOUCH"
    SN_TEMP = "SN-TEMP"
    SN_UNPRED = "SN-UNPRED"

    # Transitions (TR-, multi-select)
    TR_LOC = "TR-LOC"
    TR_SWITCH = "TR-SWITCH"
    TR_END = "TR-END"
    TR_NEW = "TR-NEW"
    TR_CHANGE = "TR-CHANGE"
    TR_WAIT = "TR-WAIT"

    # Communication (CM-, single-select)
    CM_VERBAL = "CM-VERBAL"
    CM_LIMVERBAL = "CM-LIMVERBAL"
    CM_NONVERBAL = "CM-NONVERBAL"
    CM_AAC = "CM-AAC"
    CM_MAKATON = "CM-MAKATON"
    CM_ECHO = "CM-ECHO"
    CM_MIXED = "CM-MIXED"

    # Recovery (RC-, single-select)
    RC_SHORT = "RC-SHORT"
    RC_MOD = "RC-MOD"
    RC_EXT = "RC-EXT"
    RC_VAR = "RC-VAR"

    # Triggers (TG-, parent-added day-level "today" flags; section 4.4)
    TG_HUNGER = "TG-HUNGER"
    TG_FATIGUE = "TG-FATIGUE"
    TG_ILL = "TG-ILL"
    TG_ANXIETY = "TG-ANXIETY"
    TG_MEDS = "TG-MEDS"
    TG_HOME = "TG-HOME"


def validate_single_select_tags(tags: List[Tag]) -> List[Tag]:
    """Enforce that Communication and Recovery are single-select (SeedData.md).

    Sensory (SN-) and Transitions (TR-) are multi-select; Communication (CM-) and
    Recovery (RC-) are single-select families, so at most one tag from each may be
    present. The Sensory + Transitions combined max-10 cap is UI-only (the table
    stores every selected tag), so it is not enforced here. Reused by every write
    path (care-recipient create/update and the onboarding payload) so the rule is
    defined once and holds everywhere. Raises ValueError (a 422 at the route) on a
    violation.
    """
    cm = [t for t in tags if t.value.startswith("CM-")]
    rc = [t for t in tags if t.value.startswith("RC-")]
    if len(cm) > 1:
        raise ValueError("Communication is single-select: at most one CM- tag")
    if len(rc) > 1:
        raise ValueError("Recovery is single-select: at most one RC- tag")
    return tags


class ChildProfileBase(BaseModel):
    """Fields a client may set on a care recipient."""

    name: str = Field(..., min_length=1)
    age_band: Optional[str] = None
    support_level_code: Optional[SupportLevelCode] = None
    tags: List[Tag] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _single_select_families(cls, tags: List[Tag]) -> List[Tag]:
        return validate_single_select_tags(tags)


class ChildProfileCreate(ChildProfileBase):
    """Payload to create a care recipient.

    user_id is not accepted from the client: it is taken from the authenticated
    session server-side and the RLS insert policy requires user_id == auth.uid(),
    so a row can only ever be created for the caller.
    """


class ChildProfileUpdate(BaseModel):
    """Partial update. Every field optional; id, user_id, timestamps not editable."""

    name: Optional[str] = Field(default=None, min_length=1)
    age_band: Optional[str] = None
    support_level_code: Optional[SupportLevelCode] = None
    tags: Optional[List[Tag]] = None

    @field_validator("tags")
    @classmethod
    def _single_select_families(cls, tags: Optional[List[Tag]]) -> Optional[List[Tag]]:
        if tags is None:
            return tags
        return validate_single_select_tags(tags)


class ChildProfile(ChildProfileBase):
    """The full care recipient as returned by the api (mirrors the table row)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
