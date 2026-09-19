"""The LCE Addendum worked-example scenarios (LCEEngineAddendum.md 1, 6).

The two scenarios the Addendum works through as the AUTHORITATIVE Fusion-Layer +
Specificity-Gate fixtures: `school.return_after_break` and `health.dentist_checkup`.
Their moments are transcribed VERBATIM from the Addendum (section 1 for the school
return, section 6 Example 2 for the dentist).

Why they live here and NOT as rows in knowledge_base_v1.py (the transcribed 74):
  - `school.return_after_break` (base 4/2/3/2) is a NEW example scenario, not one of
    the 74 verbatim Knowledge Base rows; adding it to the KB would change the audited
    "74 scenarios" transcription and its count guard (tests/test_seed.py).
  - `health.dentist_checkup` is in a HEALTH chapter, which is not one of the six fixed
    Life Chapters (school/career/family/social/travel/culture). A health chapter is a
    lifespan-expansion item (Decisions.md D8), out of the Wave-1 scope; forcing it into
    the six-chapter seed would fail the loader's chapter validation.

So these are authored MOMENT fixtures the pure Fusion Layer consumes directly (the
engine functions take moments + active tags, no seeded base row needed). The ~6
already-seeded scenarios that DID gain moments carry them inline on their ScenarioRow
in knowledge_base_v1.py; Wave 2 authors moments across all 74 (BuildPlan-PRDv2.md).

The `base` scores are carried for documentation + an optional tier check; the Fusion
Layer + gate do not read them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from app.models.seed import BaseScores, ScenarioMoment


@dataclass(frozen=True)
class WorkedExample:
    """An Addendum worked-example scenario: its id, base scores, and moments."""

    scenario_id: str
    base: BaseScores
    moments: Tuple[ScenarioMoment, ...]


# --- Example 1: school return after a long break (LCEEngineAddendum.md section 1) ---
# base { T: 4, S: 2, L: 3, H: 2 }; moments verbatim.
SCHOOL_RETURN_AFTER_BREAK = WorkedExample(
    scenario_id="school.return_after_break",
    base=BaseScores(temporal=4, sensory=2, logistical=3, human=2),
    moments=(
        ScenarioMoment(
            id="arrival",
            label="Arrival / playground",
            loads=["SN-CROWD", "SN-NOISE", "SN-UNPRED"],
        ),
        ScenarioMoment(
            id="assembly",
            label="First assembly",
            loads=["SN-NOISE", "SN-LIGHT", "SN-CROWD"],
        ),
        ScenarioMoment(
            id="lining_up",
            label="Lining up / registration",
            loads=["TR-WAIT", "SN-CROWD"],
        ),
        ScenarioMoment(
            id="cloakroom",
            label="Cloakroom to classroom",
            loads=["TR-LOC", "TR-SWITCH"],
        ),
        ScenarioMoment(
            id="end_of_day",
            label="Collection / decompression",
            loads=["RC-MOD", "RC-EXT", "TR-SWITCH"],
        ),
    ),
)


# --- Example 2/3: dentist check-up (LCEEngineAddendum.md section 6 Example 2) --------
# Moments: waiting_room [TR-WAIT, SN-CROWD, SN-UNPRED], chair [SN-LIGHT, SN-NOISE,
# SN-UNPRED, touch], travel [TR-LOC], post [RC-MOD]. "touch" is the SN-TOUCH tag.
DENTIST_CHECKUP = WorkedExample(
    scenario_id="health.dentist_checkup",
    base=BaseScores(temporal=3, sensory=4, logistical=3, human=2),
    moments=(
        ScenarioMoment(
            id="travel",
            label="Getting there",
            loads=["TR-LOC"],
        ),
        ScenarioMoment(
            id="waiting_room",
            label="Waiting room",
            loads=["TR-WAIT", "SN-CROWD", "SN-UNPRED"],
        ),
        ScenarioMoment(
            id="chair",
            label="In the chair",
            loads=["SN-LIGHT", "SN-NOISE", "SN-UNPRED", "SN-TOUCH"],
        ),
        ScenarioMoment(
            id="post",
            label="Afterwards",
            loads=["RC-MOD"],
        ),
    ),
)


# The canonical worked-example child "Tio" tag set (LCEEngineAddendum.md section 6).
TIO_TAGS: List[str] = [
    "SN-NOISE",
    "SN-CROWD",
    "SN-LIGHT",
    "SN-UNPRED",
    "TR-LOC",
    "TR-SWITCH",
    "TR-WAIT",
    "CM-MIXED",
    "RC-MOD",
]

WORKED_EXAMPLES: Tuple[WorkedExample, ...] = (SCHOOL_RETURN_AFTER_BREAK, DENTIST_CHECKUP)
