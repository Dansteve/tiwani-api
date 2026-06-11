"""Tag Architecture v1 (authoritative transcription): the per-tag dimension modifiers.

Deliverable B of Task 2. This is an EXACT VERBATIM TRANSCRIPTION of the full tag table
from the authoritative "TIWANI Child Profile Tag Architecture v1.0" (April 2026),
Part 2. It REPLACES the earlier TIWANI-derived v1 (authored from first principles
when the companion doc was not in the repo) and CORRECTS it where the two differ.
The engine adds these modifiers on top of the base scores (Product.md section 4.4
step 3); the engine caps the SUM of tag contributions per dimension at +2
(CAP_TAG_CONTRIBUTION_PER_DIMENSION), then caps each dimension at 5.

THE 32-TAG ARCHITECTURE (the source's five families + the SL multipliers):
  - SL multipliers (3): SL-LOW x1.0, SL-MED x1.2, SL-HIGH x1.4 (all dimensions).
    These are MULTIPLIERS, not additive modifier rows, so they are recorded here as
    SUPPORT_MULTIPLIERS, not as TagModifierRow. The engine applies them in step 2.
  - SN- Sensory (9, multi-select): each +1 Sensory; SN-UNPRED also +1 Temporal.
  - TR- Transitions (6, multi-select): TR-LOC +1 Logistical; TR-SWITCH/TR-END/TR-WAIT
    +1 Temporal; TR-NEW +1 Temporal AND +1 Sensory; TR-CHANGE +1 to ALL FOUR.
  - CM- Communication (7, single-select): CM-NONVERBAL +1 Human; CM-AAC +1 Logistical
    AND +1 Human; CM-ECHO +1 Human; CM-VERBAL / CM-LIMVERBAL / CM-MAKATON / CM-MIXED
    carry NO score (they drive strategy selection only, so they have no modifier row).
  - RC- Recovery (4, single-select): RC-SHORT 0 (no row); RC-MOD +1 Temporal;
    RC-EXT +2 Temporal; RC-VAR +1 Temporal.
  - TG- Triggers (6, parent-added day-level "today" flags; Product.md section 4.4):
    TG-HUNGER +1 Temporal; TG-FATIGUE +1 ALL; TG-ILL +2 ALL; TG-ANXIETY +1 Human AND
    +1 Sensory; TG-MEDS +1 ALL; TG-HOME +1 Temporal AND +1 Human.

CORRECTIONS vs the derived v1 (the authoritative values win):
  - SN-NOISE and SN-LIGHT are +1 (the derived v1 had them at +2). ALL SN- tags are +1.
  - SN-CROWD and SN-TOUCH are +1 Sensory ONLY (the derived v1 also added +1 Human).
  - TR-CHANGE is +1 to all four (the derived v1 had +2 Temporal only); TR-WAIT is
    +1 Temporal (the derived v1 had +2); TR-LOC is +1 Logistical only (the derived v1
    also added +1 Temporal); TR-NEW is +1 Temporal AND +1 Sensory (the derived v1 had
    +1 Logistical AND +1 Human).
  - CM-NONVERBAL is +1 Human (the derived v1 had +2); CM-AAC is +1 Logistical AND
    +1 Human (the derived v1 had +1 Human only); CM-LIMVERBAL / CM-MAKATON / CM-MIXED
    carry NO score (the derived v1 gave each +1 Human).
  - Recovery: only RC-SHORT is 0; RC-MOD +1, RC-EXT +2, RC-VAR +1 Temporal (the
    derived v1 wrongly made EVERY RC- tag 0-pressure). This is the RC correction.
  - The TG- Triggers family is NEW (it was absent from the derived v1): it is the
    section 4.4 "today" flags expressed as tags.

THE +2-PER-DIMENSION CAP. The source's modifier-logic paragraph caps the SUM of stacked
tag modifiers at +2 per dimension ("Maximum total modifier per dimension is capped at
+2"). A single tag's value is +1 or +2; when several stack on one dimension the engine
caps their SUM at +2 (applied once, in the loader's tag_contribution). A tag that
intensifies two or more dimensions appears as one TagModifierRow per dimension.

THE CALC CONFLICT (flagged for Task 12). The source's worked example (Family Wedding,
Tag doc Part 3) keeps DECIMALS after the SL multiplier and does NOT cap each dimension
at 5: base 4/4/4/4, x1.2 -> 4.8 each, +1 sensory (SN-NOISE) + 1 to all (TR-CHANGE),
final 5.8/6.8/5.8/5.8, total 24.2. Product.md section 4.4 instead ROUNDS after the
multiplier and CAPS each dimension at 5 (total stays 4 to 20). The PRD wins (CLAUDE.md
PRD-wins rule); the engine (Task 5) rounds and caps. This is the Task 12 score-
resolution decision. The modifier VALUES below are unaffected, they are the additive
+1/+2 the source states; only HOW they are combined (round + cap) is the engine's job.
"""

from __future__ import annotations

from typing import Dict, List

from app.models.seed import Dimension, TagModifierRow

# The version label travels with the data (SeedData.md: the seed is versioned; a
# value change is a new version, owned by the PRODUCT OWNER).
TAG_ARCHITECTURE_VERSION = "tag_architecture_v1"
TAG_ARCHITECTURE_PROVENANCE = (
    "Transcribed verbatim from the authoritative TIWANI LCE Complete Knowledge "
    "Base v1.0 and Child Profile Tag Architecture v1.0 (April 2026). Owner-ratifiable, "
    "swappable data: any value is owner-changeable without a code edit (a new seed "
    "version owned by the PRODUCT OWNER)."
)

# The support-level multipliers (Tag Architecture Part 2, the SL- rows). These are
# MULTIPLIERS applied to all four dimensions in LCE step 2 (Product.md section 4.4),
# not additive modifier rows, so they live here as data the engine reads, separate
# from TAG_MODIFIER_ROWS. Verbatim: SL-LOW x1.0, SL-MED x1.2, SL-HIGH x1.4.
SUPPORT_MULTIPLIERS: Dict[str, float] = {
    "SL-LOW": 1.0,
    "SL-MED": 1.2,
    "SL-HIGH": 1.4,
}

# Communication tags that carry NO pressure modifier (they drive strategy selection
# only, per the source). Listed so the intent is explicit and the loader can allow a
# CM- tag to have no modifier row without it being treated as a missing-tag error.
NO_SCORE_COMMUNICATION_TAGS: List[str] = [
    "CM-VERBAL",  # Strategy selection
    "CM-LIMVERBAL",  # Strategy selection
    "CM-MAKATON",  # Strategy selection
    "CM-MIXED",  # Strategy selection
]

# Recovery tags that carry NO pressure modifier. Per the source ONLY RC-SHORT is 0
# ("No modifier. Standard transition windows apply."); RC-MOD/RC-EXT/RC-VAR DO carry
# a Temporal modifier (this corrects the derived v1, which zeroed every RC- tag).
ZERO_PRESSURE_RECOVERY_TAGS: List[str] = [
    "RC-SHORT",  # No modifier. Standard transition windows apply.
]


# The authored modifier rows, one (tag_code, dimension, modifier) per dimension a tag
# intensifies. A tag that intensifies several dimensions appears as several rows. The
# rationale carries the source's verbatim "what it means in practice" text. CM- no-score
# tags and RC-SHORT have NO row here (0/absent modifier, allowed by the loader).
TAG_MODIFIER_ROWS: List[TagModifierRow] = [
    # =====================================================================
    # Sensory (SN-, multi-select): each +1 Sensory; SN-UNPRED also +1 Temporal.
    # =====================================================================
    TagModifierRow(
        tag_code="SN-NOISE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for any scenario with significant noise levels.",
    ),
    TagModifierRow(
        tag_code="SN-CROWD",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for any scenario in densely populated spaces.",
    ),
    TagModifierRow(
        tag_code="SN-LIGHT",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for scenarios with bright, flickering, or fluorescent lighting.",
    ),
    TagModifierRow(
        tag_code="SN-TEXTURE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for scenarios involving unfamiliar clothing, surfaces, or food.",
    ),
    TagModifierRow(
        tag_code="SN-SMELL",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for scenarios in environments with strong or unfamiliar smells.",
    ),
    TagModifierRow(
        tag_code="SN-TASTE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for scenarios involving food or eating in social contexts.",
    ),
    TagModifierRow(
        tag_code="SN-TOUCH",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for scenarios involving physical contact or crowded physical spaces.",
    ),
    TagModifierRow(
        tag_code="SN-TEMP",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Sensory score for outdoor or unfamiliar temperature environments.",
    ),
    TagModifierRow(
        tag_code="SN-UNPRED",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to both Sensory and Temporal for scenarios in unfamiliar or changeable environments.",
    ),
    TagModifierRow(
        tag_code="SN-UNPRED",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to both Sensory and Temporal for scenarios in unfamiliar or changeable environments.",
    ),
    # =====================================================================
    # Transitions (TR-, multi-select): +Temporal and/or +Logistical/+Sensory; TR-CHANGE +1 all four.
    # =====================================================================
    TagModifierRow(
        tag_code="TR-LOC",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="Add 1 to Logistical score for every scenario with two or more location changes.",
    ),
    TagModifierRow(
        tag_code="TR-SWITCH",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal score for scenarios requiring switching between different activities.",
    ),
    TagModifierRow(
        tag_code="TR-END",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal score for scenarios that require ending something the child enjoys.",
    ),
    TagModifierRow(
        tag_code="TR-NEW",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal and Sensory for scenarios involving new or unfamiliar activities.",
    ),
    TagModifierRow(
        tag_code="TR-NEW",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Temporal and Sensory for scenarios involving new or unfamiliar activities.",
    ),
    TagModifierRow(
        tag_code="TR-CHANGE",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to all four dimensions for scenarios where plans change without warning. Highest impact tag.",
    ),
    TagModifierRow(
        tag_code="TR-CHANGE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to all four dimensions for scenarios where plans change without warning. Highest impact tag.",
    ),
    TagModifierRow(
        tag_code="TR-CHANGE",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="Add 1 to all four dimensions for scenarios where plans change without warning. Highest impact tag.",
    ),
    TagModifierRow(
        tag_code="TR-CHANGE",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to all four dimensions for scenarios where plans change without warning. Highest impact tag.",
    ),
    TagModifierRow(
        tag_code="TR-WAIT",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal for scenarios with significant unstructured waiting time.",
    ),
    # =====================================================================
    # Communication (CM-, single-select): only NONVERBAL/AAC/ECHO carry a score; the rest are strategy-only (no row).
    # =====================================================================
    TagModifierRow(
        tag_code="CM-NONVERBAL",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to Human dimension. Prioritise visual and AAC-compatible strategies. Remove verbal-dependent strategies.",
    ),
    TagModifierRow(
        tag_code="CM-AAC",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="Add 1 to Logistical (device management) and Human (communication complexity). AAC-specific strategies prioritised.",
    ),
    TagModifierRow(
        tag_code="CM-AAC",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to Logistical (device management) and Human (communication complexity). AAC-specific strategies prioritised.",
    ),
    TagModifierRow(
        tag_code="CM-ECHO",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to Human dimension. Strategies account for echolalic communication patterns.",
    ),
    # =====================================================================
    # Recovery (RC-, single-select): RC-SHORT 0 (no row); MOD +1, EXT +2, VAR +1 Temporal.
    # =====================================================================
    TagModifierRow(
        tag_code="RC-MOD",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal for any scenario followed by another scheduled activity within 2 hours.",
    ),
    TagModifierRow(
        tag_code="RC-EXT",
        dimension=Dimension.TEMPORAL,
        modifier=2,
        rationale="Add 2 to Temporal for any scenario followed by another scheduled activity within 4 hours. Transition Map flags recovery window as protected time.",
    ),
    TagModifierRow(
        tag_code="RC-VAR",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal as precaution. Post-Activity Pulse used to calibrate recovery pattern over time.",
    ),
    # =====================================================================
    # Triggers (TG-, parent-added day-level "today" flags; section 4.4).
    # =====================================================================
    TagModifierRow(
        tag_code="TG-HUNGER",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal for scenarios near meal or snack times.",
    ),
    TagModifierRow(
        tag_code="TG-FATIGUE",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to all dimensions. Parent flags when child has had poor sleep. Engine increases all scores for that day.",
    ),
    TagModifierRow(
        tag_code="TG-FATIGUE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to all dimensions. Parent flags when child has had poor sleep. Engine increases all scores for that day.",
    ),
    TagModifierRow(
        tag_code="TG-FATIGUE",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="Add 1 to all dimensions. Parent flags when child has had poor sleep. Engine increases all scores for that day.",
    ),
    TagModifierRow(
        tag_code="TG-FATIGUE",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to all dimensions. Parent flags when child has had poor sleep. Engine increases all scores for that day.",
    ),
    TagModifierRow(
        tag_code="TG-ILL",
        dimension=Dimension.TEMPORAL,
        modifier=2,
        rationale="Add 2 to all dimensions. Highest risk modifier. Continuity Pivot strongly recommended.",
    ),
    TagModifierRow(
        tag_code="TG-ILL",
        dimension=Dimension.SENSORY,
        modifier=2,
        rationale="Add 2 to all dimensions. Highest risk modifier. Continuity Pivot strongly recommended.",
    ),
    TagModifierRow(
        tag_code="TG-ILL",
        dimension=Dimension.LOGISTICAL,
        modifier=2,
        rationale="Add 2 to all dimensions. Highest risk modifier. Continuity Pivot strongly recommended.",
    ),
    TagModifierRow(
        tag_code="TG-ILL",
        dimension=Dimension.HUMAN,
        modifier=2,
        rationale="Add 2 to all dimensions. Highest risk modifier. Continuity Pivot strongly recommended.",
    ),
    TagModifierRow(
        tag_code="TG-ANXIETY",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to Human and Sensory. Parent can flag this manually on any given day.",
    ),
    TagModifierRow(
        tag_code="TG-ANXIETY",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to Human and Sensory. Parent can flag this manually on any given day.",
    ),
    TagModifierRow(
        tag_code="TG-MEDS",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to all dimensions during medication change or review periods.",
    ),
    TagModifierRow(
        tag_code="TG-MEDS",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Add 1 to all dimensions during medication change or review periods.",
    ),
    TagModifierRow(
        tag_code="TG-MEDS",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="Add 1 to all dimensions during medication change or review periods.",
    ),
    TagModifierRow(
        tag_code="TG-MEDS",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to all dimensions during medication change or review periods.",
    ),
    TagModifierRow(
        tag_code="TG-HOME",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Add 1 to Temporal and Human during periods of significant home change, new sibling, house move, family change.",
    ),
    TagModifierRow(
        tag_code="TG-HOME",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Add 1 to Temporal and Human during periods of significant home change, new sibling, house move, family change.",
    ),
]
