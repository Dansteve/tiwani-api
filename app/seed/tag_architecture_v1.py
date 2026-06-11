"""Tag Architecture v1 (TIWANI-derived): the per-tag dimension modifiers.

Deliverable B of Task 2. For every one of the 26 recovered tag codes
(HardRules/Api/Modules/SeedData.md, used VERBATIM, no invented codes) this file
declares which pressure dimension(s) the tag intensifies and by how much (+1 or
+2). The engine adds these on top of the base scores (Product.md section 4.4
step 3); the engine caps the SUM of tag contributions per dimension at +2
(CAP_TAG_CONTRIBUTION_PER_DIMENSION), then caps each dimension at 5.

PROVENANCE AND CONFIDENCE. These modifier values are a TIWANI-derived v1, authored
from first principles against the shared four-dimension rubric (SeedData.md "The
shared rubric"), because the original "TIWANI Child Profile Tag Architecture v1.0"
companion document was never in the repo and the owner does not have it (Task 2
notes, Q7). Every value carries a one-line rationale below. The whole set is
labelled "TIWANI-derived v1, pending owner ratification + clinical sign-off"
(Tasks 7/12) and is stored as DATA the engine reads, so the owner can change any
cell without a code edit. This is NOT silent fabrication: it is a transparent,
ratifiable starting point with its reasoning attached.

THE TAG MODIFIER PRINCIPLE (SeedData.md). A tag adds +1 or +2 to the dimension(s)
it logically intensifies. A single tag's value is +1 or +2; when several tags
stack on one dimension the engine caps their SUM at +2 (so a child with three
sensory tags does not get +3 sensory). A tag that intensifies two dimensions
appears as two rows.

FAMILY MAPPING (refined with reasons per row below):
  - Sensory (SN-, multi-select): primarily +sensory; the ones that also bite
    socially add +human (a crowd, unexpected touch), and unpredictable sensory
    input also adds +temporal (the anticipation/timing load).
  - Transitions (TR-, multi-select): +temporal and/or +logistical (change,
    novelty, waiting); the genuinely NEW ones (new place/people) also add +human.
  - Communication (CM-, single-select): +human, scaled by how much the
    communication difference raises the in-the-moment communication demand;
    fully-verbal adds nothing.
  - Recovery (RC-, single-select): 0 PRESSURE MODIFIER (see the RECOVERY DECISION
    below). Recovery has no modifier row at all; it drives STRATEGY selection.

THE COMMUNICATION (CM-) SINGLE-SELECT DECISION. Communication is single-select: a
child has exactly one communication profile, so at most one CM- modifier is ever
applied. The values run 0 (fully verbal, no added demand) to +2 (non-verbal, the
highest in-the-moment communication demand in human-heavy settings). Because it is
single-select it never stacks with another CM- tag, so the +2 per-dimension cap is
only ever reached when a CM- modifier combines with a human-loading sensory or
transition tag, which is the correct, intended interaction.

THE RECOVERY (RC-) DECISION (documented, deliberate). Recovery describes how a
child returns to baseline AFTER stress (short, moderate, extended, or variable
recovery time), NOT the in-the-moment pressure of the activity. The four LCE
dimensions all measure in-the-moment demand, so mapping recovery onto a pressure
dimension would be modelling the wrong thing and would double-count load the
sensory/transition/communication tags already carry. The HONEST model is therefore
a 0 pressure modifier for every RC- tag: recovery contributes NO score, and instead
drives STRATEGY selection (a child with RC-EXT or RC-VAR should see recovery and
decompression strategies ranked higher, and the plan should protect recovery time).
That strategy hook is implemented when the Strategy Library lands (Product.md
section 4.10, Task 9); the seed records the decision and emits no RC- modifier row.
If the owner later ratifies a small temporal modifier for the longest-recovery tags
(the argument being that a long recovery shortens the usable day), it is a one-cell
data change here, not a code change.
"""

from __future__ import annotations

from typing import List

from app.models.seed import Dimension, TagModifierRow

# The version label travels with the data (SeedData.md: the seed is versioned; a
# value change is a new version, owned by the PRODUCT OWNER).
TAG_ARCHITECTURE_VERSION = "tag_architecture_v1"
TAG_ARCHITECTURE_PROVENANCE = (
    "TIWANI-derived v1, pending owner ratification + clinical sign-off "
    "(Tasks 7/12). Authored from the shared four-dimension rubric; the original "
    "Tag Architecture v1.0 companion doc was never in the repo (Q7). Stored as "
    "data: any value is owner-changeable without a code edit."
)

# Tag families whose tags carry a 0 pressure modifier by design (no modifier row).
# Recovery (RC-) is the honest 0-pressure family: it drives strategy selection,
# not the score (see THE RECOVERY DECISION above).
ZERO_PRESSURE_FAMILIES: List[str] = ["RC-"]


# The authored modifier rows. Each (tag_code, dimension, modifier, rationale). A
# tag that intensifies two dimensions appears twice. A tag with no row contributes
# nothing (fully-verbal communication, and every Recovery tag).
TAG_MODIFIER_ROWS: List[TagModifierRow] = [
    # =====================================================================
    # Sensory (SN-, multi-select): primarily +sensory; crowd/touch also +human;
    # unpredictable sensory also +temporal.
    # =====================================================================
    TagModifierRow(
        tag_code="SN-NOISE",
        dimension=Dimension.SENSORY,
        modifier=2,
        rationale="Noise sensitivity is a core, high-frequency sensory load; +2 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-CROWD",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="A crowd is a sensory press (bodies, sound, motion); +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-CROWD",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="A crowd is also a press of people and proximity; +1 human.",
    ),
    TagModifierRow(
        tag_code="SN-LIGHT",
        dimension=Dimension.SENSORY,
        modifier=2,
        rationale="Bright or flickering light is a strong, pervasive sensory load; +2 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-TEXTURE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Texture sensitivity bites on specific contact, narrower than ambient; +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-SMELL",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Smell sensitivity is situational and intermittent; +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-TASTE",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Taste/oral sensitivity is narrow (food, oral care); +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-TOUCH",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Unexpected touch is a sensory load; +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-TOUCH",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Unexpected touch is bound up with people and proximity; +1 human.",
    ),
    TagModifierRow(
        tag_code="SN-TEMP",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Temperature sensitivity is situational; +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-UNPRED",
        dimension=Dimension.SENSORY,
        modifier=1,
        rationale="Unpredictable sensory input is a sensory load; +1 sensory.",
    ),
    TagModifierRow(
        tag_code="SN-UNPRED",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Not knowing when sensory hits land is an anticipation/timing load; +1 temporal.",
    ),
    # =====================================================================
    # Transitions (TR-, multi-select): +temporal and/or +logistical; the genuinely
    # new ones also +human.
    # =====================================================================
    TagModifierRow(
        tag_code="TR-LOC",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="Changing location adds planning and novelty of place; +1 logistical.",
    ),
    TagModifierRow(
        tag_code="TR-LOC",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="The move itself adds timing pressure and transit; +1 temporal.",
    ),
    TagModifierRow(
        tag_code="TR-SWITCH",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Switching between activities is a pacing/timing load; +1 temporal.",
    ),
    TagModifierRow(
        tag_code="TR-END",
        dimension=Dimension.TEMPORAL,
        modifier=1,
        rationale="Endings and stopping a preferred activity are a timing/transition load; +1 temporal.",
    ),
    TagModifierRow(
        tag_code="TR-NEW",
        dimension=Dimension.LOGISTICAL,
        modifier=1,
        rationale="A new place or situation adds novelty and planning; +1 logistical.",
    ),
    TagModifierRow(
        tag_code="TR-NEW",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Newness usually means new people and social unfamiliarity; +1 human.",
    ),
    TagModifierRow(
        tag_code="TR-CHANGE",
        dimension=Dimension.TEMPORAL,
        modifier=2,
        rationale="Unexpected change to a known routine is the strongest temporal disruptor; +2 temporal.",
    ),
    TagModifierRow(
        tag_code="TR-WAIT",
        dimension=Dimension.TEMPORAL,
        modifier=2,
        rationale="Waiting is the canonical temporal pressure; +2 temporal.",
    ),
    # =====================================================================
    # Communication (CM-, single-select): +human, scaled by in-the-moment demand.
    # CM-VERBAL has no row (0 added demand).
    # =====================================================================
    TagModifierRow(
        tag_code="CM-LIMVERBAL",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Limited verbal speech raises communication demand in social settings; +1 human.",
    ),
    TagModifierRow(
        tag_code="CM-NONVERBAL",
        dimension=Dimension.HUMAN,
        modifier=2,
        rationale="Non-verbal communication is the highest in-the-moment communication demand; +2 human.",
    ),
    TagModifierRow(
        tag_code="CM-AAC",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Communicating via an AAC device adds setup and demand with new people; +1 human.",
    ),
    TagModifierRow(
        tag_code="CM-MAKATON",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Signing (Makaton) needs a receptive partner, raising demand with strangers; +1 human.",
    ),
    TagModifierRow(
        tag_code="CM-ECHO",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="Echolalia can be misread by unfamiliar people, raising social demand; +1 human.",
    ),
    TagModifierRow(
        tag_code="CM-MIXED",
        dimension=Dimension.HUMAN,
        modifier=1,
        rationale="A mixed/variable communication profile adds some demand in new settings; +1 human.",
    ),
    # =====================================================================
    # Recovery (RC-, single-select): NO modifier rows. 0 pressure by design
    # (THE RECOVERY DECISION above): recovery drives strategy selection, not score.
    # RC-SHORT, RC-MOD, RC-EXT, RC-VAR each contribute nothing to any dimension.
    # =====================================================================
]
