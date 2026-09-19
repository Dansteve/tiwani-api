"""LCE Knowledge Base v1 (authoritative transcription): the scenario matrix + strategies.

Deliverable A of Task 2. This is an EXACT VERBATIM TRANSCRIPTION of all six chapter
Pressure Dimension Scoring Matrices from the authoritative source document, the
"TIWANI LCE Complete Knowledge Base v1.0" (April 2026). It REPLACES the earlier
TIWANI-derived v1 (which was authored from first principles when the companion docs
were not in the repo). The companion docs have since arrived; these are the real
product scores, strategies, and tiers, copied cell for cell.

For each of the six fixed Life Chapters (the codes from app/models/chapters.Chapter:
career, school, family, social, travel, culture) this file carries every scenario row
from that chapter matrix: the verbatim scenario name, the four base
{temporal, sensory, logistical, human} scores (each 1 to 5, the X from the doc's
"X/5" cells), the participation tier, and the verbatim Recommended strategies list
(split on the doc's bullet separator). The engine reads these rows (Product.md section
4.4 step 1 + step 7); it never hardcodes a score.

TIER SOURCE. Five of the six chapter matrices (School, Family, Social, Travel, Culture)
carry an explicit Tier column, transcribed verbatim. The Career matrix has NO Tier
column, so its tier is DERIVED from the total band (4 to 8 Full, 9 to 13 Adapted,
14 to 20 Pivot), the same banding the LCE applies in step 6. Either way the loader
hard-fails if a stored tier does not match its total band.

RECURRING SCENARIO NAMES ARE INTENTIONAL. Some scenario names appear in more than one
chapter ("Morning routine: standard school day" is in both Career and School with the
same 3/2/3/2=10), which is correct: scenarios are keyed by (chapter, activity), so the
same name under two chapters is two distinct rows.

TRANSCRIPTION FIDELITY. Scores, totals, tiers, scenario names, and strategy text are
copied as written. The ONLY character change is the doc's en dash inside three numeric
ranges ("30-60 minutes", "60-90 minutes maximum", "3-4 hours maximum"), converted to a
hyphen to honour the repo's no-dash rule (CLAUDE.md); the numbers and meaning are
unchanged. Every row's four cells sum to the doc's stated Total (verified on extraction,
and re-checked hard-fail on load).

THE CALC CONFLICT (flagged for Task 12, the score-resolution decision). The Tag
Architecture worked example (Family Wedding) keeps DECIMALS after the support
multiplier and does NOT cap each dimension at 5 (it reaches a total of 24.2). Product.md
section 4.4 says ROUND after the multiplier and CAP each dimension at 5 (so the total
stays in 4 to 20). The PRD wins (the PRD-wins rule in CLAUDE.md): the engine (Task 5)
rounds and caps. These BASE scores are unaffected, they are whole numbers 1 to 5; the
conflict is purely about how the multiplier and tags are applied on top, which is the
engine's job, not the seed's.

NON-CLINICAL COPY (section 4.9 governs). The transcribed strategies are practical
preparation a family or an outsider can act on, carried verbatim from the source.
"""

from __future__ import annotations

from typing import List

from app.models.seed import (
    BaseScores,
    ScenarioMoment,
    ScenarioRow,
    ScenarioStrategy,
    Tier,
)
from app.seed.strategy_bodies_v1 import STRATEGY_BODIES

# The version label travels with the data (SeedData.md: the seed is versioned).
KNOWLEDGE_BASE_VERSION = "knowledge_base_v1"
KNOWLEDGE_BASE_PROVENANCE = (
    "Transcribed verbatim from the authoritative TIWANI LCE Complete Knowledge "
    "Base v1.0 and Child Profile Tag Architecture v1.0 (April 2026). Owner-ratifiable, "
    "swappable data: any value is owner-changeable without a code edit (a new seed "
    "version owned by the PRODUCT OWNER)."
)


def _strats(*items: str) -> List[ScenarioStrategy]:
    """Build the ranked strategy list from the verbatim strategy phrases.

    The source lists each strategy as a single bullet phrase, carried verbatim as the
    strategy `title` (rank 1 first, source order; the engine ranks by `rank`). The `body`
    is the meaningful expandable detail from strategy_bodies_v1.STRATEGY_BODIES, looked up
    by the phrase and falling back to the phrase itself when a body is not written, so
    coverage degrades gracefully. Every body passes the loader's non-clinical guard.
    """
    return [
        ScenarioStrategy(rank=i + 1, title=text, body=STRATEGY_BODIES.get(text, text))
        for i, text in enumerate(items)
    ]


# ===========================================================================
# SCHOOL
# ===========================================================================
SCHOOL_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="school",
        activity_code="morning-routine-standard-school-day",
        activity_name="Morning routine: standard school day",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=3, human=2),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/2/3/2, total 10, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Visual schedule for morning sequence",
            "Lay out clothes night before",
            "15-minute buffer before departure",
            "Same breakfast and route daily",
            "Low-demand conversation until out of door",
        ),
        moments=[
            ScenarioMoment(
                id="getting_ready",
                label="Waking and getting dressed",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="breakfast",
                label="Breakfast",
                loads=["SN-TASTE"],
            ),
            ScenarioMoment(
                id="out_the_door",
                label="Heading out the door",
                loads=["TR-LOC"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="morning-routine-child-already-dysregulated",
        activity_name="Morning routine: child already dysregulated",
        base_scores=BaseScores(temporal=5, sensory=3, logistical=4, human=3),
        stated_total=15,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 5/3/4/3, total 15, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Activate reduced-expectation morning plan",
            "Contact school early, flag difficult start",
            "Minimum viable morning, what must happen vs what can flex",
            "Sensory regulation support before leaving",
            "Consider delayed start if school can accommodate",
        ),
        moments=[
            ScenarioMoment(
                id="settling",
                label="Settling a rocky start",
                loads=["SN-UNPRED"],
            ),
            ScenarioMoment(
                id="getting_ready",
                label="Getting dressed and ready",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="flexing_the_plan",
                label="Flexing the plan for a later start",
                loads=["TR-CHANGE"],
            ),
            ScenarioMoment(
                id="out_the_door",
                label="Getting out the door",
                loads=["TR-LOC"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="school-gate-drop-off-routine",
        activity_name="School gate drop-off: routine",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=2, human=3),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/2/3, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Consistent handoff script with school staff",
            "Same drop-off points and routine daily",
            "Reassurance phrase prepared",
            "Parent decompression before starting work",
            "Named staff member receives child",
        ),
        moments=[
            ScenarioMoment(
                id="at_the_gate",
                label="Arriving at the gate",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="saying_goodbye",
                label="Saying goodbye",
                loads=["TR-END"],
            ),
            ScenarioMoment(
                id="going_in",
                label="Being handed over to staff",
                loads=["TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="school-gate-drop-off-child-refusing-or-distressed",
        activity_name="School gate drop-off: child refusing or distressed",
        base_scores=BaseScores(temporal=5, sensory=4, logistical=3, human=4),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 5/4/3/4, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Pre-agreed distress protocol with school SENCO",
            "Continuity Card sent to school in advance",
            "Employer notified of possible late start",
            "Do not force, activate school's agreed alternative",
            "Parent self-care protocol for high-distress drop-offs",
        ),
        moments=[
            ScenarioMoment(
                id="at_the_gate",
                label="Arriving when it is already hard",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="the_separation",
                label="The separation itself",
                loads=["TR-END", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="stepping_back",
                label="Stepping back to the agreed plan",
                loads=["TR-CHANGE"],
            ),
            ScenarioMoment(
                id="afterwards",
                label="Winding down afterwards",
                loads=["RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="school-transport-routine-bus-or-taxi",
        activity_name="School transport: routine bus or taxi",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=2),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/2, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Familiar driver and route",
            "Visual timer for journey length",
            "Sensory comfort item in bag",
            "Predictable collection point",
        ),
        moments=[
            ScenarioMoment(
                id="boarding",
                label="Getting on",
                loads=["TR-LOC"],
            ),
            ScenarioMoment(
                id="the_journey",
                label="The journey",
                loads=["SN-NOISE", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="arriving",
                label="Arriving at school",
                loads=["TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="playground-arrival-open-unstructured-time",
        activity_name="Playground arrival: open unstructured time",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=2, human=4),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/2/4, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Structured arrival activity rather than free play",
            "Named peer or buddy system if available",
            "Sensory reduction strategy, headphones, quiet corner",
            "Staff supervision at arrival",
        ),
        moments=[
            ScenarioMoment(
                id="gate",
                label="Coming through the gate",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="free_play",
                label="Open, unstructured play",
                loads=["SN-UNPRED", "SN-NOISE", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="line_up",
                label="Lining up to go in",
                loads=["TR-WAIT", "SN-CROWD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="lesson-transitions-between-classes-or-spaces",
        activity_name="Lesson transitions: between classes or spaces",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=2),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/3/2, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Transition warning 5 and 2 minutes before",
            "Visual schedule showing next activity",
            "Familiar route between spaces",
            "Staff escort if needed",
            "Fidget or comfort item for transition periods",
        ),
        moments=[
            ScenarioMoment(
                id="ending_the_lesson",
                label="Wrapping up the current lesson",
                loads=["TR-END"],
            ),
            ScenarioMoment(
                id="moving_between",
                label="Moving between spaces",
                loads=["TR-LOC", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="settling_next",
                label="Settling into the next activity",
                loads=["TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="breaktime-and-lunchtime",
        activity_name="Breaktime and lunchtime",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=2, human=4),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/2/4, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Identified quiet space available",
            "Structured activity option during break",
            "Familiar lunch routine, same food, same place",
            "Sensory kit accessible",
            "Named adult available if needed",
        ),
        moments=[
            ScenarioMoment(
                id="dining_hall",
                label="Dining hall",
                loads=["SN-NOISE", "SN-CROWD", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="playground",
                label="Playground break",
                loads=["SN-UNPRED", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="back_to_class",
                label="Settling back to class",
                loads=["TR-SWITCH", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="return-to-school-after-absence-short",
        activity_name="Return to school after absence: short",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=3),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/3/3, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Advance communication with school",
            "Gradual reintegration plan if needed",
            "Familiar face to meet child at gate",
            "Updated Continuity Card if anything has changed",
        ),
        moments=[
            ScenarioMoment(
                id="arriving_back",
                label="Arriving back at the gate",
                loads=["SN-CROWD", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="back_into_class",
                label="Settling back into class",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="winding_down",
                label="Winding down after the first day back",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="return-to-school-after-long-break-holidays",
        activity_name="Return to school after long break: holidays",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=4, human=3),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/4/3, total 14, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Transition preparation starting week before return",
            "Visit to school environment if possible",
            "Visual schedule of new term",
            "Reduced expectation first week",
            "Parent-school communication plan agreed in advance",
        ),
        moments=[
            ScenarioMoment(
                id="arrival",
                label="Arrival and the playground",
                loads=["SN-CROWD", "SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="assembly",
                label="First assembly",
                loads=["SN-NOISE", "SN-LIGHT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="lining_up",
                label="Lining up and registration",
                loads=["TR-WAIT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="cloakroom",
                label="Cloakroom to classroom",
                loads=["TR-LOC", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="end_of_day",
                label="Collection and decompression",
                loads=["RC-MOD", "TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="unexpected-change-at-school-supply-teacher-room-change",
        activity_name="Unexpected change at school: supply teacher, room change",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=3),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/3/3, total 14, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "School to notify parent same morning where possible",
            "Child prepared with visual explanation of change",
            "Sensory regulation strategy available",
            "Named adult to check in with child during transition",
        ),
        moments=[
            ScenarioMoment(
                id="finding_out",
                label="Finding out the plan has changed",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_new_setup",
                label="A different teacher or room",
                loads=["SN-UNPRED", "TR-LOC"],
            ),
            ScenarioMoment(
                id="staying_settled",
                label="Staying settled through the change",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="parent-school-meeting-routine-review",
        activity_name="Parent-school meeting: routine review",
        base_scores=BaseScores(temporal=2, sensory=1, logistical=2, human=4),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/1/2/4, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Prepare agenda and questions in advance",
            "Bring evidence of child's experience, LCI data if available",
            "Request written follow-up after meeting",
            "Bring a support person if needed",
        ),
        moments=[
            ScenarioMoment(
                id="the_wait",
                label="Waiting for the meeting",
                loads=["TR-WAIT"],
            ),
            ScenarioMoment(
                id="afterwards",
                label="Winding down afterwards",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="parent-school-meeting-conflict-or-crisis",
        activity_name="Parent-school meeting: conflict or crisis",
        base_scores=BaseScores(temporal=4, sensory=1, logistical=3, human=5),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/1/3/5, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Request meeting in writing, creates a record",
            "Bring written notes and evidence",
            "Know your rights; EHCP, SEND Code of Practice",
            "Request independent support if needed; IPSEA, SENDIASS",
            "Allow decompression time after meeting",
        ),
        moments=[
            ScenarioMoment(
                id="getting_there",
                label="Getting there",
                loads=["TR-LOC"],
            ),
            ScenarioMoment(
                id="the_wait",
                label="Waiting for a tense meeting",
                loads=["TR-WAIT", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="afterwards",
                label="Decompression afterwards",
                loads=["RC-EXT"],
            ),
        ],
    ),
]


# ===========================================================================
# CAREER
# The Career matrix has no Tier column; tier is derived from the total band.
# ===========================================================================
CAREER_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="career",
        activity_code="morning-routine-standard-school-day",
        activity_name="Morning routine: standard school day",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=3, human=2),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/2/3/2, total 10, tier Adapted (derived from the total band).",
        strategies=_strats(
            "Visual schedule for morning sequence",
            "Lay out clothes night before",
            "Build in 15-minute buffer before departure",
            "Reduce decision points, same breakfast, same route",
        ),
        moments=[
            ScenarioMoment(
                id="getting_going",
                label="Waking and getting going",
                loads=["TR-SWITCH", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="getting_ready",
                label="Getting dressed and breakfast",
                loads=["SN-TEXTURE", "SN-TASTE"],
            ),
            ScenarioMoment(
                id="out_the_door",
                label="Heading out the door on time",
                loads=["TR-LOC", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="morning-routine-after-difficult-night",
        activity_name="Morning routine: after difficult night",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=3, human=3),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/3/3, total 13, tier Adapted (derived from the total band).",
        strategies=_strats(
            "Activate modified morning plan, reduce expectations",
            "Contact employer/manager early if capacity is reduced",
            "Identify minimum viable morning, what must happen vs what can flex",
            "Sensory regulation support before leaving house",
        ),
        moments=[
            ScenarioMoment(
                id="slow_start",
                label="A slower, harder start",
                loads=["TR-SWITCH", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="regulating",
                label="Helping them settle before leaving",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="getting_out",
                label="Getting out the door",
                loads=["TR-LOC", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="school-drop-off-routine-day",
        activity_name="School drop-off: routine day",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=2, human=2),
        stated_total=8,
        tier=Tier.FULL,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/2/2, total 8, tier Full Engagement (derived from the total band).",
        strategies=_strats(
            "Consistent handoff script with school staff",
            "Same drop-off points and routine daily",
            "Reassurance phrase prepared for child",
            "Parent decompression window before starting work",
        ),
        moments=[
            ScenarioMoment(
                id="the_journey",
                label="The trip to school",
                loads=["TR-LOC"],
            ),
            ScenarioMoment(
                id="the_gate",
                label="Arriving at the gate",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="saying_goodbye",
                label="Saying goodbye",
                loads=["TR-END", "TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="school-drop-off-after-incident-or-meltdown",
        activity_name="School drop-off: after incident or meltdown",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=3),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/3/3, total 14, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "Pre-agreed emergency handoff protocol with school",
            "Continuity Card sent to school in advance",
            "Employer notified of possible late start",
            "Parent self-regulation before entering workplace or calls",
        ),
        moments=[
            ScenarioMoment(
                id="the_journey",
                label="The trip in",
                loads=["TR-LOC", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_gate",
                label="Arriving at a busy gate",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="saying_goodbye",
                label="Saying goodbye at the gate",
                loads=["TR-END", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="settling_after",
                label="Giving them time to settle",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="unexpected-school-call-during-work-hours",
        activity_name="Unexpected school call during work hours",
        base_scores=BaseScores(temporal=5, sensory=2, logistical=4, human=4),
        stated_total=15,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 5/2/4/4, total 15, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "Pre-written employer communication template ready",
            "Backup care contact list maintained and current",
            "Flexible working arrangement documented in advance",
            "Employer briefed on SEND caring context via Continuity Card",
        ),
        moments=[
            ScenarioMoment(
                id="the_call",
                label="Taking the call",
                loads=["TR-CHANGE"],
            ),
            ScenarioMoment(
                id="handover",
                label="Leaving work to collect",
                loads=["TR-LOC", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="refocus",
                label="Getting back to work afterwards",
                loads=["RC-MOD", "RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="school-collection-routine",
        activity_name="School collection: routine",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=2, human=2),
        stated_total=8,
        tier=Tier.FULL,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/2/2, total 8, tier Full Engagement (derived from the total band).",
        strategies=_strats(
            "Consistent collection time and routine",
            "Decompression activity prepared for child",
            "Work wrap-up protocol, clear end-of-day signal",
        ),
        moments=[
            ScenarioMoment(
                id="the_pickup",
                label="Meeting them at pick-up",
                loads=["SN-CROWD", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="the_journey_home",
                label="The journey home",
                loads=["TR-LOC", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="decompression",
                label="Winding down after school",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="school-collection-child-had-difficult-day",
        activity_name="School collection: child had difficult day",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=3, human=4),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/3/4, total 14, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "School to send advance warning where possible",
            "De-escalation plan ready for collection",
            "Evening work commitments flagged as at risk",
            "Recovery space planned for child on arrival home",
        ),
        moments=[
            ScenarioMoment(
                id="the_pickup",
                label="Collecting after a hard day",
                loads=["SN-CROWD", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_journey_home",
                label="The journey home",
                loads=["TR-LOC", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="recovery_at_home",
                label="Recovery space at home",
                loads=["RC-EXT", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="working-from-home-child-present",
        activity_name="Working from home: child present",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=4, human=5),
        stated_total=17,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/4/5, total 17, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "Structured child activity plan for work hours",
            "Clear physical boundary between work space and child space",
            "Employer aware of caring context",
            "Reduced meeting load on days child is home",
            "Emergency sensory kit accessible without entering work space",
        ),
        moments=[
            ScenarioMoment(
                id="focused_work",
                label="Trying to focus or take a meeting",
                loads=["SN-NOISE", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="lunch_break",
                label="Lunch and breaks together",
                loads=["SN-TASTE", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="end_of_day",
                label="Winding down at the end of the day",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="important-meeting-or-deadline-care-disruption",
        activity_name="Important meeting or deadline: care disruption",
        base_scores=BaseScores(temporal=5, sensory=2, logistical=5, human=4),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 5/2/5/4, total 16, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "Pre-meeting preparation and backup plan documented",
            "Employer or manager briefed in advance on risk",
            "Backup care contact activated",
            "Modified participation option, can you dial in rather than attend?",
            "Post-disruption recovery plan for work task",
        ),
        moments=[
            ScenarioMoment(
                id="the_disruption",
                label="When the plan changes suddenly",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_handover",
                label="Handing over to backup care",
                loads=["TR-SWITCH", "TR-NEW"],
            ),
            ScenarioMoment(
                id="settling_after",
                label="Settling the child again afterwards",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="performance-review-or-career-conversation",
        activity_name="Performance review or career conversation",
        base_scores=BaseScores(temporal=3, sensory=1, logistical=2, human=4),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/1/2/4, total 10, tier Adapted (derived from the total band).",
        strategies=_strats(
            "Prepare evidence of contribution despite caring context",
            "Continuity Card summarising employer support needs ready",
            "Request flexible timing, not Monday morning",
            "Manager briefed on SEND caring context in advance",
        ),
        moments=[
            ScenarioMoment(
                id="the_run_up",
                label="The run-up on the day",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="care_during",
                label="Care covered while you talk",
                loads=["TR-LOC", "TR-NEW"],
            ),
            ScenarioMoment(
                id="refocus_after",
                label="Getting back into the day after",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="training-conference-or-away-day",
        activity_name="Training, conference, or away day",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=4, human=3),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/4/3, total 14, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "Care cover arranged and confirmed in writing",
            "Emergency contact plan in place",
            "Employer aware of caring context",
            "Modified participation option, partial attendance?",
            "Recovery time built in for following day",
        ),
        moments=[
            ScenarioMoment(
                id="the_run_up",
                label="Preparing them for the day",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="care_cover",
                label="Being with the cover carer",
                loads=["TR-LOC", "TR-NEW"],
            ),
            ScenarioMoment(
                id="reunion",
                label="Reconnecting at the end",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="childcare-breakdown-backup-needed",
        activity_name="Childcare breakdown: backup needed",
        base_scores=BaseScores(temporal=5, sensory=2, logistical=5, human=4),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 5/2/5/4, total 16, tier Continuity Pivot (derived from the total band).",
        strategies=_strats(
            "Emergency care contact list, minimum three options",
            "Employer emergency protocol pre-agreed",
            "Work from home fallback if child manageable at home",
            "Carer's Leave entitlement documented and ready to invoke",
            "Proactive employer communication, early notice always better",
        ),
        moments=[
            ScenarioMoment(
                id="it_falls_through",
                label="When care falls through",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="finding_cover",
                label="Sorting backup at short notice",
                loads=["TR-LOC", "TR-NEW"],
            ),
            ScenarioMoment(
                id="settling_the_child",
                label="Settling the child into the change",
                loads=["TR-SWITCH", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="return-to-work-after-caring-absence",
        activity_name="Return to work after caring absence",
        base_scores=BaseScores(temporal=4, sensory=2, logistical=3, human=4),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/2/3/4, total 13, tier Adapted (derived from the total band).",
        strategies=_strats(
            "Phased return plan agreed with employer",
            "Updated Continuity Card for employer",
            "Reduced meeting load in first two weeks",
            "Check-in with manager scheduled",
            "Care infrastructure confirmed stable before return date",
        ),
        moments=[
            ScenarioMoment(
                id="new_routine",
                label="Settling into the new routine",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="daily_handover",
                label="The care handover each day",
                loads=["TR-LOC", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="reconnecting",
                label="Reconnecting after work",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="applying-for-a-new-role-or-promotion",
        activity_name="Applying for a new role or promotion",
        base_scores=BaseScores(temporal=3, sensory=1, logistical=3, human=3),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/1/3/3, total 10, tier Adapted (derived from the total band).",
        strategies=_strats(
            "Document caring responsibilities as context not limitation",
            "Research employer's flexible working policy in advance",
            "Prepare Continuity Card for new employer context",
            "Identify caring-friendly employers, NHS, Civil Service, larger employers with DE&I commitments",
        ),
        moments=[
            ScenarioMoment(
                id="interview_cover",
                label="Care cover for interviews",
                loads=["TR-LOC", "TR-NEW"],
            ),
            ScenarioMoment(
                id="a_possible_change",
                label="Preparing for a change in routine",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="new_rhythm",
                label="Settling a new rhythm together",
                loads=["TR-SWITCH", "RC-MOD"],
            ),
        ],
    ),
]


# ===========================================================================
# FAMILY (Family Life & Routine)
# ===========================================================================
FAMILY_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="family",
        activity_code="morning-routine-stable-day",
        activity_name="Morning routine: stable day",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=3, human=1),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/2/3/1, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Visual morning schedule",
            "Pre-prepared clothes and bag",
            "Same sequence every day",
            "No non-essential decision points",
            "15-minute buffer before departure",
        ),
        moments=[
            ScenarioMoment(
                id="waking_up",
                label="Waking and getting going",
                loads=["TR-SWITCH", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="getting_dressed",
                label="Getting dressed",
                loads=["SN-TEXTURE", "SN-TOUCH"],
            ),
            ScenarioMoment(
                id="breakfast",
                label="Breakfast",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="out_the_door",
                label="Heading out on time",
                loads=["TR-LOC", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="morning-routine-sleep-disrupted-night",
        activity_name="Morning routine: sleep-disrupted night",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=3, human=2),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/3/2, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Reduced expectation morning, what is the minimum viable exit?",
            "Comfort-led breakfast, familiar, low-demand",
            "Sensory regulation support before school",
            "Contact school early if child is not in best shape",
        ),
        moments=[
            ScenarioMoment(
                id="hard_wake",
                label="A harder wake-up",
                loads=["TR-SWITCH", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="comfort_breakfast",
                label="A comfort-led breakfast",
                loads=["SN-TASTE", "SN-TEXTURE"],
            ),
            ScenarioMoment(
                id="regulating",
                label="Helping them settle",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="getting_out",
                label="Getting out the door",
                loads=["TR-LOC", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="mealtime-routine-meal",
        activity_name="Mealtime: routine meal",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=2, human=2),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/2/2, total 10, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Same foods, same plate, same seating",
            "Remove sensory irritants, smells, textures, sounds",
            "Low-demand conversation during meal",
            "Accepted refusal without pressure where safe",
        ),
        moments=[
            ScenarioMoment(
                id="coming_to_table",
                label="Coming to the table",
                loads=["TR-SWITCH", "TR-END"],
            ),
            ScenarioMoment(
                id="the_food",
                label="The food itself",
                loads=["SN-TASTE", "SN-TEXTURE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="sitting_through",
                label="Sitting through the meal",
                loads=["SN-NOISE", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="mealtime-introducing-new-food-or-eating-out",
        activity_name="Mealtime: introducing new food or eating out",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=3),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/3/3, total 14, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Preparation in advance, show picture of food or venue",
            "Familiar safe food always available as backup",
            "Reduced expectation, presence at table is success",
            "Sensory preparation for unfamiliar environment",
        ),
        moments=[
            ScenarioMoment(
                id="getting_there",
                label="Getting somewhere new",
                loads=["TR-LOC", "TR-NEW"],
            ),
            ScenarioMoment(
                id="the_new_food",
                label="Trying something new",
                loads=["SN-TASTE", "SN-SMELL", "SN-TEXTURE"],
            ),
            ScenarioMoment(
                id="the_room",
                label="An unfamiliar, busy room",
                loads=["SN-NOISE", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="staying_at_table",
                label="Staying at the table",
                loads=["TR-WAIT", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="bedtime-routine-typical-evening",
        activity_name="Bedtime routine: typical evening",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=2, human=1),
        stated_total=8,
        tier=Tier.FULL,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/2/2/1, total 8, tier Full Engagement (transcribed verbatim).",
        strategies=_strats(
            "Same sequence every night",
            "Wind-down period 30-60 minutes before bed",
            "Sensory comfort: weighted blanket, white noise, dimmed light",
            "Low stimulation activities only after dinner",
            "Same sleep environment every night",
        ),
    ),
    ScenarioRow(
        chapter="family",
        activity_code="bedtime-child-resistant-or-dysregulated",
        activity_name="Bedtime: child resistant or dysregulated",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=3, human=2),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/3/2, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Extend wind-down period",
            "Remove stimulating activities earlier",
            "Sensory regulation support bath, massage, deep pressure",
            "No screen time 90 minutes before bed",
            "Parent self-regulation, this is the hardest part of the day",
        ),
        moments=[
            ScenarioMoment(
                id="ending_the_day",
                label="Ending the fun of the day",
                loads=["TR-END", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="long_wind_down",
                label="A longer wind-down",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="settling_to_sleep",
                label="Settling down to sleep",
                loads=["SN-TOUCH", "SN-TEXTURE"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="night-waking-child-cannot-resettle",
        activity_name="Night waking: child cannot resettle",
        base_scores=BaseScores(temporal=4, sensory=2, logistical=2, human=3),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/2/2/3, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Pre-agreed night protocol, what parent does, in what order",
            "Minimal engagement, keep it dark, calm, and quiet",
            "Return to bed without prolonged interaction",
            "Document frequency for healthcare team if persistent",
        ),
        moments=[
            ScenarioMoment(
                id="the_waking",
                label="Waking in the night",
                loads=["SN-UNPRED", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="resettling",
                label="Trying to resettle",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="back_to_sleep",
                label="Getting back to sleep",
                loads=["RC-VAR", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="weekend-unstructured-day",
        activity_name="Weekend: unstructured day",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=2),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/3/2, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Create loose structure, not rigid, but predictable rhythm",
            "Identify anchor activities that ground the day",
            "Build in quiet time and sensory recovery periods",
            "Reduce social demands on high-regulation-need days",
        ),
        moments=[
            ScenarioMoment(
                id="open_stretches",
                label="Long open stretches",
                loads=["SN-UNPRED", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="switching_activities",
                label="Moving between activities",
                loads=["TR-SWITCH", "TR-END"],
            ),
            ScenarioMoment(
                id="quiet_time",
                label="Built-in quiet time",
                loads=["RC-MOD", "SN-NOISE"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="holiday-from-school-first-day",
        activity_name="Holiday from school: first day",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=2),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/3/2, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Prepare child in advance for change of routine",
            "Visual schedule for holiday day",
            "Familiar morning routine maintained where possible",
            "Lower activity expectations, decompression day",
        ),
        moments=[
            ScenarioMoment(
                id="routine_changes",
                label="The routine changes",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="open_day",
                label="A more open day",
                loads=["SN-UNPRED", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="decompression",
                label="A decompression day",
                loads=["RC-MOD", "RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="routine-disruption-family-illness-or-absence",
        activity_name="Routine disruption: family illness or absence",
        base_scores=BaseScores(temporal=4, sensory=2, logistical=4, human=3),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/2/4/3, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Identify minimum viable routine for disrupted day",
            "Communicate change to child visually and early",
            "Activate backup support if available",
            "Reduce all non-essential demands",
        ),
        moments=[
            ScenarioMoment(
                id="the_change",
                label="When the usual routine breaks",
                loads=["TR-CHANGE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="different_faces",
                label="Different people helping out",
                loads=["TR-LOC", "TR-NEW"],
            ),
            ScenarioMoment(
                id="holding_steady",
                label="Keeping a minimum routine",
                loads=["TR-SWITCH", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="sibling-conflict-high-intensity",
        activity_name="Sibling conflict: high intensity",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=2, human=5),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/2/5, total 14, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Physical separation strategy, identified calm space for each child",
            "Reduce sensory load in shared spaces",
            "Pre-agreed conflict de-escalation plan",
            "Parent self-regulation support",
        ),
        moments=[
            ScenarioMoment(
                id="as_it_builds",
                label="As it builds",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="separating",
                label="Moving to separate spaces",
                loads=["TR-LOC", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="calming_down",
                label="Calming down after",
                loads=["RC-MOD", "RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="hygiene-routine-bath-or-shower-resistance",
        activity_name="Hygiene routine: bath or shower resistance",
        base_scores=BaseScores(temporal=3, sensory=5, logistical=2, human=2),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/5/2/2, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Sensory-adapted approach, water temperature, pressure, products",
            "Visual schedule for hygiene sequence",
            "Child agency over sequence where possible",
            "Alternative hygiene strategies if bath/shower not possible",
        ),
        moments=[
            ScenarioMoment(
                id="getting_started",
                label="Getting started",
                loads=["TR-SWITCH", "TR-END"],
            ),
            ScenarioMoment(
                id="the_water",
                label="Water and washing",
                loads=["SN-TOUCH", "SN-TEMP"],
            ),
            ScenarioMoment(
                id="products_and_textures",
                label="Soap, products and textures",
                loads=["SN-SMELL", "SN-TEXTURE"],
            ),
            ScenarioMoment(
                id="drying_off",
                label="Drying off and dressing",
                loads=["SN-TEXTURE", "SN-TOUCH"],
            ),
        ],
    ),
]


# ===========================================================================
# SOCIAL (Social & Community)
# ===========================================================================
SOCIAL_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="social",
        activity_code="playdate-familiar-child-home-setting",
        activity_name="Playdate: familiar child, home setting",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=1, human=3),
        stated_total=8,
        tier=Tier.FULL,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/1/3, total 8, tier Full Engagement (transcribed verbatim).",
        strategies=_strats(
            "Structured activity prepared",
            "Familiar environment, child's home",
            "Short duration,60-90 minutes maximum",
            "Parent nearby but not hovering",
            "Clear end signal agreed in advance",
        ),
        moments=[
            ScenarioMoment(
                id="warming_up",
                label="Warming up at the start",
                loads=["SN-UNPRED"],
            ),
            ScenarioMoment(
                id="playing_together",
                label="Playing together",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="goodbye",
                label="Ending and goodbye",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="playdate-unfamiliar-child-or-new-location",
        activity_name="Playdate: unfamiliar child or new location",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=2, human=4),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/2/4, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Pre-visit to location if possible",
            "Shorter duration than usual",
            "Familiar activity structure",
            "Parent present throughout",
            "Exit phrase prepared",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving somewhere new",
                loads=["TR-LOC", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="meeting_them",
                label="Meeting an unfamiliar child",
                loads=["SN-UNPRED"],
            ),
            ScenarioMoment(
                id="playing_together",
                label="Playing together",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="heading_home",
                label="Ending and heading home",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="birthday-party-small-familiar-children",
        activity_name="Birthday party: small, familiar children",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=2, human=4),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/2/4, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Arrive early before crowd builds",
            "Identify quiet space in advance",
            "Continuity Card shared with host",
            "Exit plan agreed: we may need to leave early'",
            "Familiar food option confirmed",
        ),
        moments=[
            ScenarioMoment(
                id="arrival",
                label="Arrival",
                loads=["SN-CROWD", "SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="games",
                label="Games and activities",
                loads=["SN-UNPRED", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="food_and_cake",
                label="Food and cake",
                loads=["SN-TASTE", "SN-SMELL", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="goodbye",
                label="Leaving and wind-down",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="birthday-party-large-or-unfamiliar-setting",
        activity_name="Birthday party: large or unfamiliar setting",
        base_scores=BaseScores(temporal=4, sensory=5, logistical=3, human=4),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/5/3/4, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Modified attendance, arrive for cake only or specific activity",
            "Sensory kit packed, headphones, sunglasses, fidget",
            "Quiet space identified before arriving",
            "Exit phrase practised",
            "Parent stays throughout",
            "Success defined as: child attended, not child enjoyed every minute",
        ),
        moments=[
            ScenarioMoment(
                id="arrival",
                label="Arrival",
                loads=["SN-CROWD", "SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_thick_of_it",
                label="The busiest part",
                loads=["SN-NOISE", "SN-LIGHT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="food_and_cake",
                label="Food and cake",
                loads=["SN-TASTE", "SN-SMELL", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="a_quiet_break",
                label="A quiet break",
                loads=["RC-MOD"],
            ),
            ScenarioMoment(
                id="leaving",
                label="Leaving and wind-down",
                loads=["TR-END", "RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="family-gathering-small-familiar-group",
        activity_name="Family gathering, small familiar group",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=2, human=3),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/2/3, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Familiar setting where possible",
            "Child's safe foods available",
            "Quiet retreat space identified",
            "Duration limited, leave before child is exhausted",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving and hellos",
                loads=["SN-CROWD"],
            ),
            ScenarioMoment(
                id="the_meal",
                label="The meal",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="a_quiet_break",
                label="A quiet break",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="family-gathering-large-or-extended-family",
        activity_name="Family gathering: large or extended family",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=5),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/3/5, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Pre-arrival briefing for family members, Continuity Card",
            "Quiet room identified and off-limits to others",
            "Clear exit plan, car parked for easy departure",
            "Modified attendance: attend part only",
            "Child's comfort items brought",
            "Permission given explicitly to leave without explanation",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving and greetings",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="hellos_and_hugs",
                label="Hellos and hugs",
                loads=["SN-TOUCH", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="the_meal",
                label="The meal",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="quiet_retreat",
                label="A quiet retreat",
                loads=["RC-MOD"],
            ),
            ScenarioMoment(
                id="leaving",
                label="Leaving and wind-down",
                loads=["TR-END", "RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="community-event-small-local",
        activity_name="Community event, small local",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=3),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/3, total 10, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Preview event in advance if possible",
            "Attend off-peak if timing flexible",
            "Sensory kit available",
            "Clear exit plan",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="during_the_event",
                label="During the event",
                loads=["SN-NOISE", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="heading_off",
                label="Heading off",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="community-event-large-festival-or-fair",
        activity_name="Community event, large festival or fair",
        base_scores=BaseScores(temporal=4, sensory=5, logistical=3, human=4),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/5/3/4, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Attend at quietest time: early opening",
            "Sensory reduction: headphones, sunglasses",
            "Map of venue in advance",
            "Identified quiet zone",
            "Short duration planned, not full day",
            "Modified participation, part of event only",
        ),
        moments=[
            ScenarioMoment(
                id="getting_in",
                label="Getting in and queues",
                loads=["SN-CROWD", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="crowds_and_noise",
                label="The crowds and noise",
                loads=["SN-NOISE", "SN-CROWD", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="food_stalls",
                label="Food stalls",
                loads=["SN-SMELL", "SN-TASTE"],
            ),
            ScenarioMoment(
                id="quiet_zone",
                label="The quiet zone",
                loads=["RC-MOD"],
            ),
            ScenarioMoment(
                id="leaving",
                label="Leaving and wind-down",
                loads=["TR-END", "RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="eating-out-familiar-restaurant",
        activity_name="Eating out: familiar restaurant",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=2),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/2, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Familiar restaurant, same place, same table if possible",
            "Menu reviewed in advance",
            "Off-peak timing",
            "Sensory adjustments, quieter area requested",
        ),
        moments=[
            ScenarioMoment(
                id="arrival_seating",
                label="Arriving and being seated",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="waiting_for_food",
                label="Waiting for food",
                loads=["TR-WAIT", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="the_meal",
                label="The meal itself",
                loads=["SN-TASTE", "SN-TEXTURE"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="eating-out-new-restaurant-or-occasion",
        activity_name="Eating out: new restaurant or occasion",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=3),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/3/3, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Menu reviewed online in advance",
            "Call ahead, explain needs, request quiet table",
            "Continuity Card for staff if helpful",
            "Safe food backup carried",
            "Short visit planned, not extended dining",
        ),
        moments=[
            ScenarioMoment(
                id="arriving_and_seated",
                label="Arriving and being seated",
                loads=["SN-CROWD", "SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="waiting_for_food",
                label="Waiting for food",
                loads=["TR-WAIT", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="the_meal",
                label="The meal",
                loads=["SN-TASTE", "SN-TEXTURE"],
            ),
            ScenarioMoment(
                id="heading_home",
                label="Winding down afterwards",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="public-transport-routine-journey",
        activity_name="Public transport, routine journey",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=2),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/2, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Same route and timing",
            "Sensory kit, headphones, comfort item",
            "Visual journey timer",
            "Off-peak where possible",
        ),
        moments=[
            ScenarioMoment(
                id="waiting_to_board",
                label="Waiting to board",
                loads=["TR-WAIT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="the_journey",
                label="The journey",
                loads=["SN-NOISE", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="our_stop",
                label="Getting off at our stop",
                loads=["TR-SWITCH", "TR-LOC"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="public-transport-unfamiliar-route-or-busy",
        activity_name="Public transport, unfamiliar route or busy",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=2),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/3/2, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Practise route in advance",
            "Avoid peak times",
            "Sensory preparation",
            "Arrival buffer time built in",
        ),
        moments=[
            ScenarioMoment(
                id="the_wait",
                label="Waiting and working out the route",
                loads=["TR-WAIT", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="busy_boarding",
                label="A busy boarding",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="the_journey",
                label="The journey",
                loads=["SN-NOISE", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="finding_our_stop",
                label="Finding our stop",
                loads=["TR-SWITCH", "SN-UNPRED"],
            ),
        ],
    ),
]


# ===========================================================================
# TRAVEL (Travel & Holiday)
# ===========================================================================
TRAVEL_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="travel",
        activity_code="car-journey-short-familiar-route-under-1-hour",
        activity_name="Car journey, short, familiar route under 1 hour",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=1, human=1),
        stated_total=6,
        tier=Tier.FULL,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/1/1, total 6, tier Full Engagement (transcribed verbatim).",
        strategies=_strats(
            "Familiar music or audio",
            "Comfort items in reach",
            "Journey timer visual",
            "Snacks and drinks packed",
            "Predictable destination",
        ),
        moments=[
            ScenarioMoment(
                id="setting_off",
                label="Getting in and setting off",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="the_drive",
                label="The drive itself",
                loads=["TR-WAIT", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="arriving",
                label="Arriving and getting out",
                loads=["TR-END", "TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="car-journey-long-over-2-hours",
        activity_name="Car journey, long, over 2 hours",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=1),
        stated_total=10,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/3/1, total 10, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Pre-planned stop schedule, same stops every time",
            "Sensory kit in back seat",
            "Audio entertainment prepared",
            "Snacks and meals pre-packed",
            "Arrival time communicated clearly",
            "Recovery time on arrival",
        ),
        moments=[
            ScenarioMoment(
                id="setting_off",
                label="Getting going",
                loads=["TR-SWITCH"],
            ),
            ScenarioMoment(
                id="the_long_stretch",
                label="The long stretch of driving",
                loads=["TR-WAIT", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="rest_stops",
                label="Stopping and starting again",
                loads=["TR-SWITCH", "TR-LOC"],
            ),
            ScenarioMoment(
                id="arrival_recovery",
                label="Arriving and settling",
                loads=["RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="train-journey-short-familiar",
        activity_name="Train journey, short, familiar",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=2),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/2, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Seat reservation, same carriage type",
            "Quiet coach if available",
            "Sensory kit",
            "Journey timer",
        ),
        moments=[
            ScenarioMoment(
                id="platform",
                label="On the platform",
                loads=["TR-WAIT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="boarding",
                label="Getting on and finding seats",
                loads=["SN-CROWD", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="the_ride",
                label="The journey itself",
                loads=["SN-NOISE", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="train-journey-long-or-unfamiliar",
        activity_name="Train journey, long or unfamiliar",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=2),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/3/2, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Reserve specific seats in advance",
            "Quiet carriage reserved",
            "Full sensory kit",
            "Familiar food packed",
            "Visual journey schedule",
            "Plan for delays, what we do if train is late",
        ),
        moments=[
            ScenarioMoment(
                id="station_navigation",
                label="Finding the right platform",
                loads=["TR-LOC", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="boarding",
                label="Boarding and finding seats",
                loads=["SN-CROWD", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="the_long_ride",
                label="The long ride",
                loads=["SN-NOISE", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="delays_changes",
                label="If the train is delayed",
                loads=["TR-CHANGE", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="airport-departure-standard",
        activity_name="Airport, departure, standard",
        base_scores=BaseScores(temporal=4, sensory=5, logistical=5, human=3),
        stated_total=17,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/5/5/3, total 17, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Request hidden disability lanyard or airport assistance",
            "Arrive early, minimum 3 hours for sensory adjustment",
            "Security fast-tracks if available",
            "Identify quiet zones before arrival",
            "Visual airport schedule prepared",
            "Familiar food packed for waiting time",
            "Sensory kit immediately accessible, not in hold luggage",
        ),
        moments=[
            ScenarioMoment(
                id="check_in_bag_drop",
                label="Check-in and bag drop",
                loads=["SN-CROWD", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="security",
                label="Going through security",
                loads=["SN-UNPRED", "SN-CROWD", "SN-TOUCH", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="waiting_at_gate",
                label="Waiting at the gate",
                loads=["TR-WAIT", "SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="boarding",
                label="Boarding the plane",
                loads=["SN-CROWD", "TR-WAIT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="airport-departure-child-highly-anxious-or-dysregulated",
        activity_name="Airport, departure, child highly anxious or dysregulated",
        base_scores=BaseScores(temporal=5, sensory=5, logistical=5, human=4),
        stated_total=19,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 5/5/5/4, total 19, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Continuity Pivot consideration, is travel possible today?",
            "All sensory reduction strategies activated",
            "Minimum viable airport plan, security and gate only",
            "Airport assistance formally requested in advance",
            "Decompression strategy for waiting",
            "Parent self-regulation plan, this is the hardest travel scenario",
        ),
        moments=[
            ScenarioMoment(
                id="arrival_terminal",
                label="Arriving at the terminal",
                loads=["SN-CROWD", "SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="security",
                label="Getting through security",
                loads=["SN-UNPRED", "SN-CROWD", "SN-TOUCH"],
            ),
            ScenarioMoment(
                id="waiting_at_gate",
                label="The wait before boarding",
                loads=["TR-WAIT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="boarding",
                label="Boarding",
                loads=["SN-CROWD", "TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="flight-short-haul-under-3-hours",
        activity_name="Flight, short haul under 3 hours",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=2),
        stated_total=12,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/3/2, total 12, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Seat selection, window for view or aisle for exit",
            "Sensory kit in hand luggage",
            "Familiar entertainment downloaded offline",
            "Familiar snacks packed",
            "Visual flight duration timer",
            "Explain sounds, engines, pressure changes, landing",
        ),
        moments=[
            ScenarioMoment(
                id="boarding_settling",
                label="Boarding and getting settled",
                loads=["SN-CROWD", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="takeoff",
                label="Take-off",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="in_the_air",
                label="The flight itself",
                loads=["TR-WAIT", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="landing",
                label="Landing",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="flight-long-haul-over-5-hours",
        activity_name="Flight, long haul over 5 hours",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=4, human=2),
        stated_total=14,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/4/2, total 14, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Night flight if child sleeps on planes",
            "Bassinette or extra space if available",
            "Full sensory kit",
            "Multiple entertainment options downloaded",
            "Sleep aids, eye mask, noise cancelling, familiar blanket",
            "Meal preferences pre-ordered",
            "Recovery day built into itinerary on arrival",
        ),
        moments=[
            ScenarioMoment(
                id="boarding_settling",
                label="Boarding and settling in",
                loads=["SN-CROWD", "TR-SWITCH"],
            ),
            ScenarioMoment(
                id="takeoff",
                label="Take-off",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_long_hours",
                label="The long hours in the cabin",
                loads=["TR-WAIT", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="meals_onboard",
                label="Meals on board",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="arrival_recovery",
                label="Arriving and recovering",
                loads=["RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="hotel-stay-familiar-hotel-or-chain",
        activity_name="Hotel stay, familiar hotel or chain",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=2),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/2, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Same hotel chain or room type where possible",
            "Request quiet room away from lifts and street",
            "Bring familiar bedding items",
            "Familiar food options confirmed before arrival",
        ),
        moments=[
            ScenarioMoment(
                id="checking_in",
                label="Checking in and finding the room",
                loads=["TR-LOC", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="the_room",
                label="Settling into the room",
                loads=["SN-UNPRED", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="first_night",
                label="The first night's sleep",
                loads=["SN-TEXTURE", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="mealtimes",
                label="Meals at the hotel",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="hotel-stay-unfamiliar-or-holiday-let",
        activity_name="Hotel stay, unfamiliar or holiday let",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=2),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/3/2, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Photos of accommodation reviewed before arrival",
            "Bring familiar bedding, towels, food items",
            "Establish familiar routine on first night",
            "Identify nearest quiet outdoor space",
            "Kitchen access preferred, enables familiar meals",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving somewhere new",
                loads=["SN-UNPRED", "TR-LOC"],
            ),
            ScenarioMoment(
                id="exploring_the_space",
                label="Getting to know the space",
                loads=["SN-SMELL", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="first_night",
                label="The first night",
                loads=["SN-TEXTURE", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="mealtimes",
                label="Meals here",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="holiday-day-structured-activity",
        activity_name="Holiday day, structured activity",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=2),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/2, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Activity reviewed in advance",
            "Sensory kit packed",
            "Exit plan agreed",
            "Duration limited, not full day",
        ),
        moments=[
            ScenarioMoment(
                id="getting_there",
                label="Getting there",
                loads=["TR-LOC", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_activity",
                label="The activity itself",
                loads=["SN-UNPRED", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="heading_home",
                label="Ending and heading home",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="holiday-day-theme-park-or-busy-attraction",
        activity_name="Holiday day, theme park or busy attraction",
        base_scores=BaseScores(temporal=4, sensory=5, logistical=4, human=3),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/5/4/3, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Disability access scheme registered in advance",
            "Arrive at opening, lowest crowd density",
            "Full sensory kit",
            "Map of venue and quiet zones",
            "Short stay planned,3-4 hours maximum",
            "Modified participation, some rides not all",
            "Recovery day following",
        ),
        moments=[
            ScenarioMoment(
                id="arrival_entry",
                label="Arriving and getting in",
                loads=["SN-CROWD", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="queues_for_rides",
                label="Queuing for rides",
                loads=["TR-WAIT", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="rides_and_shows",
                label="On the rides and at shows",
                loads=["SN-NOISE", "SN-UNPRED", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="busy_open_areas",
                label="Moving through the crowds",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="leaving_recovery",
                label="Leaving and recovering",
                loads=["RC-EXT", "TR-END"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="return-home-from-holiday",
        activity_name="Return home from holiday",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=3, human=1),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/2/3/1, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Prepare child for return in advance",
            "Familiar home routine reinstated immediately",
            "Low expectation day after return",
            "School return preparation begins day after arrival home",
        ),
        moments=[
            ScenarioMoment(
                id="packing_up",
                label="Packing up to leave",
                loads=["TR-END", "TR-CHANGE"],
            ),
            ScenarioMoment(
                id="the_journey_back",
                label="The journey home",
                loads=["TR-WAIT", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="back_home",
                label="Settling back in at home",
                loads=["TR-SWITCH", "RC-MOD"],
            ),
        ],
    ),
]


# ===========================================================================
# CULTURE (Culture & Faith)
# ===========================================================================
CULTURE_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="culture",
        activity_code="weekly-religious-service-familiar-smaller-congregation",
        activity_name="Weekly religious service, familiar, smaller congregation",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=2, human=3),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/2/3, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Same seat, same position every week",
            "Quiet space identified, vestibule, side room, car",
            "Modified participation, attend part of service only",
            "Continuity Card shared with faith leader or community coordinator",
            "Exit without explanation normalised in advance",
        ),
        moments=[
            ScenarioMoment(
                id="arriving_greeting",
                label="Arriving and greetings",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="during_service",
                label="During the service",
                loads=["SN-NOISE", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="standing_sitting_transitions",
                label="The stand-up, sit-down parts",
                loads=["TR-SWITCH", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="leaving",
                label="Leaving quietly",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="weekly-religious-service-large-or-high-sensory",
        activity_name="Weekly religious service, large or high sensory",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=2, human=3),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/2/3, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Arrive after music starts if music is high-pressure",
            "Sit near exit",
            "Full sensory kit, head phones, sunglasses, fidget",
            "Quiet room identified and accessible",
            "Modified attendance, shorter duration",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="the_music",
                label="The music and singing",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="the_crowd",
                label="In among the congregation",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="leaving",
                label="Leaving and winding down",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="special-religious-occasion-eid-christmas-easter-diwali",
        activity_name="Special religious occasion, Eid, Christmas, Easter, Diwali",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=4),
        stated_total=15,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/3/4, total 15, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Advance preparation, what will happen, in what order",
            "Visual schedule of ceremony or celebration",
            "Shorter attendance planned",
            "Familiar people positioned near child",
            "Quiet exit strategy agreed in advance",
            "Familiar food available",
        ),
        moments=[
            ScenarioMoment(
                id="the_gathering",
                label="The big gathering",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="the_ceremony",
                label="The ceremony or main event",
                loads=["SN-UNPRED", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="the_rituals",
                label="The lights, fireworks or music",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="festive_meal",
                label="The festive meal",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="leaving",
                label="The quiet exit",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="cultural-celebration-family-led-at-home",
        activity_name="Cultural celebration, family-led at home",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=4),
        stated_total=11,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/3/2/4, total 11, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Child's safe foods available",
            "Quiet space in home identified",
            "Duration of gathering limited",
            "Child given permission to withdraw without consequence",
        ),
        moments=[
            ScenarioMoment(
                id="guests_arriving",
                label="Guests arriving",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="the_celebration",
                label="The celebration itself",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_food",
                label="The food and eating together",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="needing_a_break",
                label="Needing to step away",
                loads=["RC-MOD", "TR-END"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="cultural-celebration-community-venue-large",
        activity_name="Cultural celebration, community venue, large",
        base_scores=BaseScores(temporal=4, sensory=5, logistical=3, human=4),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/5/3/4, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Preview venue in advance if possible",
            "Arrive early before crowd builds",
            "Quiet room identified and reserved if possible",
            "Sensory kit fully packed",
            "Modified participation, attend part only",
            "Continuity Card shared with hosts or organisers",
        ),
        moments=[
            ScenarioMoment(
                id="arriving_venue",
                label="Arriving at the venue",
                loads=["TR-LOC", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="the_crowd",
                label="The building crowd",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="music_and_dancing",
                label="Music, drumming or dancing",
                loads=["SN-NOISE", "SN-LIGHT"],
            ),
            ScenarioMoment(
                id="the_food",
                label="The shared food",
                loads=["SN-TASTE", "SN-SMELL"],
            ),
            ScenarioMoment(
                id="stepping_out",
                label="Stepping out for a break",
                loads=["RC-MOD", "TR-END"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="faith-community-group-or-class-children-s-group",
        activity_name="Faith community group or class, children's group",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=2, human=3),
        stated_total=9,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 2/2/2/3, total 9, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Familiar adults in group",
            "Structured activity, predictable format each week",
            "Shorter session if available",
            "Named contact for parent communication",
        ),
        moments=[
            ScenarioMoment(
                id="drop_off",
                label="Being dropped off",
                loads=["TR-SWITCH", "TR-LOC"],
            ),
            ScenarioMoment(
                id="group_activity",
                label="The group activity",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="pick_up",
                label="Being collected",
                loads=["TR-END", "TR-SWITCH"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="rites-of-passage-baptism-bar-mitzvah-confirmation-naming-ceremony",
        activity_name="Rites of passage, baptism, bar mitzvah, confirmation, naming ceremony",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=5),
        stated_total=16,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/4/3/5, total 16, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Preparation visits to venue in advance",
            "Visual schedule of ceremony",
            "Child's role explained clearly and simply",
            "Quiet space available throughout",
            "Modified participation option discussed with faith leader",
            "Continuity Card for family members attending",
            "Post-event recovery time planned",
        ),
        moments=[
            ScenarioMoment(
                id="arriving_venue",
                label="Arriving at the venue",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="being_the_centre",
                label="Being the centre of attention",
                loads=["SN-UNPRED", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="the_ceremony",
                label="The ceremony itself",
                loads=["TR-WAIT", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_celebration_after",
                label="The celebration afterwards",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="recovery_after",
                label="Winding down afterwards",
                loads=["RC-EXT"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="community-funeral-or-memorial-service",
        activity_name="Community funeral or memorial service",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=3, human=5),
        stated_total=15,
        tier=Tier.PIVOT,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 4/3/3/5, total 15, tier Continuity Pivot (transcribed verbatim).",
        strategies=_strats(
            "Prepare child honestly and age-appropriately",
            "Short attendance only, child does not need to stay for full service",
            "Sensory kit available",
            "Quiet exit arranged",
            "Familiar adult designated to support child throughout",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving at the service",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="the_service",
                label="During the service",
                loads=["TR-WAIT", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="the_feeling_in_the_room",
                label="The feeling in the room",
                loads=["SN-UNPRED", "SN-CROWD"],
            ),
            ScenarioMoment(
                id="quiet_exit",
                label="Slipping out for a break",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="cultural-or-faith-trip-pilgrimage-heritage-site-visit",
        activity_name="Cultural or faith trip: pilgrimage, heritage site visit",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=4, human=3),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/3/4/3, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Preview destination visually",
            "Sensory kit packed",
            "Journey preparation, see Travel chapter",
            "Short visit planned",
            "Exit plan agreed",
        ),
        moments=[
            ScenarioMoment(
                id="the_journey",
                label="The journey there",
                loads=["TR-LOC", "TR-WAIT"],
            ),
            ScenarioMoment(
                id="arriving_site",
                label="Arriving at the site",
                loads=["SN-CROWD", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="moving_around",
                label="Walking around the site",
                loads=["SN-CROWD", "TR-LOC"],
            ),
            ScenarioMoment(
                id="heading_back",
                label="Heading back",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="community-fundraiser-or-social-event",
        activity_name="Community fundraiser or social event",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=2, human=4),
        stated_total=13,
        tier=Tier.ADAPTED,
        rationale="Authoritative base scores temporal/sensory/logistical/human = 3/4/2/4, total 13, tier Adapted (transcribed verbatim).",
        strategies=_strats(
            "Preview format and venue",
            "Arrive at quieter time",
            "Modified attendance, part of event",
            "Sensory kit",
            "Permission to leave without explanation",
        ),
        moments=[
            ScenarioMoment(
                id="arriving",
                label="Arriving",
                loads=["SN-CROWD", "SN-NOISE"],
            ),
            ScenarioMoment(
                id="the_main_event",
                label="The main part of the event",
                loads=["SN-NOISE", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="mingling",
                label="Mingling and small talk",
                loads=["SN-CROWD", "SN-UNPRED"],
            ),
            ScenarioMoment(
                id="slipping_away",
                label="Leaving when it's enough",
                loads=["TR-END", "RC-MOD"],
            ),
        ],
    ),
]


# All chapters' scenarios in one ordered list (the loader's source of truth). The
# chapter order matches app/models/chapters.Chapter (School first).
ALL_SCENARIOS: List[ScenarioRow] = (
    SCHOOL_SCENARIOS
    + CAREER_SCENARIOS
    + FAMILY_SCENARIOS
    + SOCIAL_SCENARIOS
    + TRAVEL_SCENARIOS
    + CULTURE_SCENARIOS
)
