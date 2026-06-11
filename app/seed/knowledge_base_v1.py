"""LCE Knowledge Base v1 (TIWANI-derived): the scenario matrix + strategies.

Deliverable A of Task 2. For each of the six fixed Life Chapters (school, career,
family, social, travel, culture, the codes from app/models/chapters_v3.Chapter)
this file authors a representative set of high-frequency real scenarios a
Coordinator prepares for. For each scenario: the four base
{temporal, sensory, logistical, human} scores (1 to 5), a one-line rationale
tying the scores to the rubric anchors, and 3 to 5 RANKED starter strategies
written so an outsider could act on them (the section 4.6 Continuity Card voice).
The engine reads these rows (Product.md section 4.4 step 1 + step 7); it never
hardcodes a score.

PROVENANCE AND CONFIDENCE. These base scores and strategies are a TIWANI-derived
v1, authored from first principles against the shared four-dimension rubric
(HardRules/Api/Modules/SeedData.md "The shared rubric"), because the original
"TIWANI LCE Complete Knowledge Base v1.0" companion document was never in the repo
and the owner does not have it (Task 2 notes, Q7). The whole set is labelled
"TIWANI-derived v1, pending owner ratification + clinical sign-off" (Tasks 7/12)
and is stored as DATA the engine reads, so the owner can change any base score,
rationale, or strategy without a code edit. This is a transparent, ratifiable
starting point with its reasoning attached, not silent fabrication.

THE BASE SCORE IS CHILD-AGNOSTIC. A base score is the INHERENT demand of the
activity for a typical additional-needs child at a NEUTRAL profile. The engine
applies the support multiplier (section 4.4 step 2) and the per-tag modifiers
(step 3) ON TOP, so the base never bakes in a particular child's support level or
tags. The rubric anchors used for every score:
  - temporal: 1 short/predictable/no waiting, 3 moderate duration or some queuing,
    5 long with lots of waiting and highly unpredictable timing.
  - sensory: 1 calm/quiet/controlled, 3 moderate (a classroom, a cafe),
    5 intense/unpredictable (fireworks, a busy theme park).
  - logistical: 1 familiar place/no kit/simple, 3 some planning/transport/novelty,
    5 unfamiliar place/heavy planning/equipment/transport.
  - human: 1 familiar people/low demand, 3 some new people or moderate social
    demand, 5 many strangers/high communication/performance/observation demand.

CHILD-FIRST MVP, LIFESPAN-READY SCHEMA. The scenarios are child-first for the MVP
(Decisions.md D8 is the full lifespan), but the row shape (a (chapter, activity)
with four base scores + strategies) is general: adult and elder scenarios drop in
later under the same chapters without a schema change. Where a scenario is
transition-aged (a young person's first job, a college open day) it already
stretches toward adulthood.

NON-CLINICAL COPY (section 4.9 governs). No strategy uses diagnosis, symptom,
condition, or treatment language. Strategies are practical preparation a family or
an outsider can act on.
"""

from __future__ import annotations

from typing import List

from app.models.seed import BaseScores, ScenarioRow, ScenarioStrategy

# The version label travels with the data (SeedData.md: the seed is versioned).
KNOWLEDGE_BASE_VERSION = "knowledge_base_v1"
KNOWLEDGE_BASE_PROVENANCE = (
    "TIWANI-derived v1, pending owner ratification + clinical sign-off "
    "(Tasks 7/12). Authored from the shared four-dimension rubric; the original "
    "LCE Complete Knowledge Base v1.0 companion doc was never in the repo (Q7). "
    "Stored as data: any base score or strategy is owner-changeable without a "
    "code edit."
)


def _s(rank: int, title: str, body: str) -> ScenarioStrategy:
    """Terse constructor for a ranked strategy (keeps the matrix readable)."""
    return ScenarioStrategy(rank=rank, title=title, body=body)


# ===========================================================================
# SCHOOL
# ===========================================================================
SCHOOL_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="school",
        activity_code="first-day-new-school",
        activity_name="First day at a new school",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=5, human=5),
        rationale=(
            "A long unfamiliar day (temporal 4) in a busy building (sensory 4), a new "
            "place with a new route and kit (logistical 5), and all-new people and "
            "staff observing (human 5)."
        ),
        strategies=[
            _s(1, "Visit before day one", "Walk the route and see the building once before the first day so it is not all new at once."),
            _s(2, "A photo map", "Make a simple photo card of the entrance, the classroom, the toilets, and one named adult to find."),
            _s(3, "Name one safe adult", "Agree one staff member they can go to, and tell that adult in advance."),
            _s(4, "Short first day if allowed", "Ask whether a shorter first day or a staggered start is possible."),
            _s(5, "Plan the reunion", "Tell them exactly where and when you will meet at the end so the day has a clear finish."),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="school-trip",
        activity_name="School trip",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=4, human=3),
        rationale=(
            "A long out-of-routine day (temporal 4) somewhere busy (sensory 4) that "
            "needs transport and kit (logistical 4), with mostly familiar peers and "
            "staff (human 3)."
        ),
        strategies=[
            _s(1, "Get the itinerary", "Ask staff for the timings and stops so you can walk through the day in advance."),
            _s(2, "Pack a known comfort", "Send a familiar item, snack, or ear defenders that help in a loud space."),
            _s(3, "Agree a quiet-out signal", "Set a signal with staff for needing a quieter moment, and where that would be."),
            _s(4, "Name the travel plan", "Explain the coach or transport and who they sit with before the day."),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="exam-assessment",
        activity_name="Exam or assessment",
        base_scores=BaseScores(temporal=4, sensory=2, logistical=3, human=4),
        rationale=(
            "A timed, wait-heavy session (temporal 4) in a usually quiet room (sensory "
            "2), with some setup (logistical 3) and the demand of being assessed and "
            "observed (human 4)."
        ),
        strategies=[
            _s(1, "Confirm any arrangements", "Check what access arrangements are in place (extra time, a separate room) and that staff know."),
            _s(2, "Practise the format", "Do one low-stakes run of the same format so the shape of it is familiar."),
            _s(3, "A clear finish line", "Make sure they know how long it lasts and what happens straight after."),
            _s(4, "Plan the wait", "Have a calm plan for the lining-up and waiting before it starts."),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="assembly",
        activity_name="Whole-school assembly",
        base_scores=BaseScores(temporal=2, sensory=4, logistical=1, human=3),
        rationale=(
            "A short, predictable slot (temporal 2) in a loud echoing hall packed with "
            "children (sensory 4), no kit or travel (logistical 1), and a crowd to sit "
            "among (human 3)."
        ),
        strategies=[
            _s(1, "Sit at the edge", "Ask for a seat on the end of a row or near the door for an easier exit."),
            _s(2, "Ear defenders ready", "Have ear defenders or a quiet fidget to hand for the noisiest moments."),
            _s(3, "Know the running order", "Tell them what assembly involves and roughly how long, so the noise has an end."),
            _s(4, "An agreed exit", "Agree with staff that stepping out for a moment is allowed and how to do it."),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="pe-swimming",
        activity_name="PE or swimming",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=4, human=4),
        rationale=(
            "A timed lesson with changing either side (temporal 3), a loud echoing or "
            "wet space (sensory 4), kit and changing logistics (logistical 4), and "
            "physical exposure and performance in front of peers (human 4)."
        ),
        strategies=[
            _s(1, "Changing made easy", "Sort the kit the night before and agree where and how they change with the least fuss."),
            _s(2, "Preview the space", "Describe the noise and echo of the pool or hall so it is expected."),
            _s(3, "A role if sitting out", "If joining in is hard that day, agree a helping role so they are not singled out."),
            _s(4, "Warm-down plan", "Plan a calm few minutes to reset afterwards before the next lesson."),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="fire-drill",
        activity_name="Fire drill",
        base_scores=BaseScores(temporal=2, sensory=5, logistical=1, human=2),
        rationale=(
            "Brief but unannounced (temporal 2), a sudden very loud alarm (sensory 5), "
            "no kit (logistical 1), and a familiar group moving together (human 2)."
        ),
        strategies=[
            _s(1, "Warn if you can", "Ask staff to give a quiet heads-up before a planned drill where possible."),
            _s(2, "Ear defenders nearby", "Keep ear defenders somewhere they can be grabbed quickly."),
            _s(3, "Rehearse the route", "Walk the evacuation route calmly once so the steps are known when the alarm sounds."),
            _s(4, "A familiar adult close", "Agree which adult stays near them during a drill."),
        ],
    ),
    ScenarioRow(
        chapter="school",
        activity_code="substitute-teacher",
        activity_name="Substitute teacher",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=1, human=4),
        rationale=(
            "An unexpected change to the usual routine (temporal 3) in the familiar "
            "classroom (sensory 2, logistical 1), but a new adult in charge with "
            "different expectations (human 4)."
        ),
        strategies=[
            _s(1, "Flag it early if known", "If you know in advance, tell them a different teacher is coming and that the rules are the same."),
            _s(2, "A handover note", "Ask that a short note on what helps is left for the substitute."),
            _s(3, "Keep one anchor the same", "Keep one familiar routine (the same seat, the same start) steady through the change."),
            _s(4, "Name a fallback adult", "Agree another known staff member they can check in with if needed."),
        ],
    ),
]


# ===========================================================================
# CAREER (transition-aged and first-work scenarios; lifespan-ready)
# ===========================================================================
CAREER_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="career",
        activity_code="work-experience-day",
        activity_name="Work-experience day",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=4, human=4),
        rationale=(
            "A full unfamiliar working day (temporal 4) in a moderate workplace "
            "(sensory 3), a new place to travel to with new routines (logistical 4), "
            "and new colleagues and being watched (human 4)."
        ),
        strategies=[
            _s(1, "Pre-visit or call ahead", "Visit or phone the placement first to learn the start time, the door, and who to ask for."),
            _s(2, "Write the day down", "Make a simple plan of arrival, breaks, lunch, and finish so the shape is known."),
            _s(3, "Name a point of contact", "Agree one named person at the placement to go to with questions."),
            _s(4, "Plan the journey", "Do a practice run of the travel so the route is not a new thing on the day."),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="college-open-day",
        activity_name="College open day",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=4, human=4),
        rationale=(
            "A few busy hours (temporal 3) in a large crowded venue (sensory 4), a new "
            "site to navigate (logistical 4), with lots of new people and talking to "
            "staff (human 4)."
        ),
        strategies=[
            _s(1, "Get the map and plan", "Pick in advance the two or three stands or rooms that matter, so it is not the whole site at once."),
            _s(2, "Go at a quieter time", "Aim for the start or end of the day when it is less packed."),
            _s(3, "Prepare the questions", "Write the questions down so they do not have to be thought up on the spot."),
            _s(4, "Agree a break spot", "Pick a calmer area to step out to between stands."),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="first-interview",
        activity_name="First interview",
        base_scores=BaseScores(temporal=3, sensory=2, logistical=3, human=5),
        rationale=(
            "A short slot with anxious waiting beforehand (temporal 3) in a usually "
            "quiet room (sensory 2), some travel and dress logistics (logistical 3), "
            "and high communication and being assessed by strangers (human 5)."
        ),
        strategies=[
            _s(1, "Practise out loud", "Rehearse a few likely questions and answers so the talking is not all new."),
            _s(2, "Arrive with time to spare", "Plan to get there early so the wait is calm, not rushed."),
            _s(3, "Bring a prompt card", "A small card of key points to glance at can steady the nerves."),
            _s(4, "Agree a wind-down after", "Plan something low-key straight after to come down from the demand."),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="first-job-shift",
        activity_name="A young person's first job shift",
        base_scores=BaseScores(temporal=4, sensory=3, logistical=4, human=4),
        rationale=(
            "A long shift with new pacing (temporal 4) in a moderately busy workplace "
            "(sensory 3), a new place and rota to manage (logistical 4), and new "
            "colleagues, customers, and a manager (human 4)."
        ),
        strategies=[
            _s(1, "Walk through shift one", "Ask the manager to talk through the first shift step by step beforehand."),
            _s(2, "Know the breaks", "Find out when breaks are and where to go, so there is a known reset point."),
            _s(3, "One go-to colleague", "Agree one person to check things with so they are not guessing alone."),
            _s(4, "A calm start routine", "Set a steady before-work routine so the day starts the same each time."),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="careers-meeting",
        activity_name="Careers or transition meeting",
        base_scores=BaseScores(temporal=2, sensory=2, logistical=2, human=4),
        rationale=(
            "A short scheduled meeting (temporal 2) in a quiet room (sensory 2) needing "
            "little setup (logistical 2), but talking with professionals about the "
            "future (human 4)."
        ),
        strategies=[
            _s(1, "Agree the agenda first", "Ask what will be covered so it is not an open-ended conversation."),
            _s(2, "Bring notes", "Write down the points and questions in advance to take the pressure off speaking."),
            _s(3, "Bring a supporter", "Have a trusted person there to help carry the conversation."),
            _s(4, "Keep it short", "Ask for a focused, time-limited meeting rather than a long one."),
        ],
    ),
    ScenarioRow(
        chapter="career",
        activity_code="workplace-induction",
        activity_name="Workplace induction or training",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=4),
        rationale=(
            "A half or full day of new information (temporal 3) in a moderate setting "
            "(sensory 3), a new place and materials (logistical 3), and a group of new "
            "people and a trainer (human 4)."
        ),
        strategies=[
            _s(1, "Ask for materials early", "Request the slides or handbook ahead so the content is not all new on the day."),
            _s(2, "Sit where it suits", "Pick a seat near the door or away from the busiest part of the room."),
            _s(3, "Permission to step out", "Agree it is fine to take a short break during a long session."),
            _s(4, "A recap afterwards", "Plan to go over the key points calmly afterwards rather than holding it all at once."),
        ],
    ),
]


# ===========================================================================
# FAMILY (Family Life & Routine)
# ===========================================================================
FAMILY_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="family",
        activity_code="haircut",
        activity_name="Haircut",
        base_scores=BaseScores(temporal=2, sensory=4, logistical=2, human=3),
        rationale=(
            "A short appointment with some waiting (temporal 2), strong sensory input "
            "from clippers, hair, and touch (sensory 4), a familiar trip (logistical "
            "2), and a stranger working close to the face (human 3)."
        ),
        strategies=[
            _s(1, "Same barber, quiet slot", "Book the same person at the quietest time so it is familiar and calm."),
            _s(2, "Preview the tools", "Show the clippers and let them hear the buzz before it starts."),
            _s(3, "Bring a distraction", "Have a favourite video or fidget for the chair."),
            _s(4, "Agree a stop signal", "Set a way to pause if it gets too much, and tell the barber."),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="dentist",
        activity_name="Dentist visit",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=4),
        rationale=(
            "An appointment with a waiting room (temporal 3), strong sensory input "
            "(light, sounds, taste, touch in the mouth; sensory 4), travel and an "
            "unfamiliar surgery setting (logistical 3), and an unfamiliar professional "
            "very close (human 4)."
        ),
        strategies=[
            _s(1, "Ask for a familiarisation visit", "Request a first visit just to sit in the chair with nothing done."),
            _s(2, "First or last appointment", "Book when the waiting room is emptiest to cut the wait."),
            _s(3, "Sunglasses for the light", "Bring sunglasses for the overhead light and ear defenders for the sounds."),
            _s(4, "Agree a hand-up pause", "Set a raise-your-hand signal to pause, and check the dentist will honour it."),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="gp-visit",
        activity_name="GP visit",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=2, human=4),
        rationale=(
            "An appointment with an uncertain wait (temporal 3), a moderately busy "
            "waiting room (sensory 3), a familiar-enough trip (logistical 2), and "
            "talking to and being examined by a professional (human 4)."
        ),
        strategies=[
            _s(1, "Note what to cover", "Write the reasons for the visit down in advance to ease the talking."),
            _s(2, "Ask to wait elsewhere", "Ask reception if you can wait outside or in the car and be called."),
            _s(3, "Explain what will happen", "Describe the likely steps (talk, maybe listen to the chest) so it is expected."),
            _s(4, "Bring a comfort item", "Have a familiar object for the waiting and the appointment."),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="blood-test-vaccination",
        activity_name="Blood test or vaccination",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=4),
        rationale=(
            "A short procedure with an anxious wait (temporal 3), a sharp sensory event "
            "with touch and a needle (sensory 4), an unfamiliar surgery trip (logistical "
            "3), and a professional doing something uncomfortable up close (human 4)."
        ),
        strategies=[
            _s(1, "Be honest and brief", "Explain simply and truthfully what happens and that it is quick."),
            _s(2, "Ask about numbing cream", "Ask in advance whether a numbing cream can be used and applied in time."),
            _s(3, "Plan the distraction", "Have something absorbing to look at or hold during the moment itself."),
            _s(4, "A reward to aim for", "Agree a small thing to do straight after to mark it being over."),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="routine-change",
        activity_name="A change to the daily routine",
        base_scores=BaseScores(temporal=4, sensory=2, logistical=2, human=2),
        rationale=(
            "A disruption to the expected order of the day (temporal 4) in familiar "
            "surroundings (sensory 2, logistical 2) with familiar people (human 2); the "
            "load is almost all in the timing and predictability."
        ),
        strategies=[
            _s(1, "Warn early and clearly", "Tell them about the change as far ahead as you can, simply and specifically."),
            _s(2, "Show the new plan", "Use a visual or written order of the new day so it is concrete."),
            _s(3, "Keep anchors fixed", "Hold one or two familiar routines steady through the change."),
            _s(4, "Name when normal returns", "Say clearly when the usual routine comes back."),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="house-move",
        activity_name="A house move",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=5, human=3),
        rationale=(
            "A drawn-out, high-disruption event (temporal 4) with upheaval, boxes, and "
            "noise (sensory 4), the heaviest possible planning and logistics (logistical "
            "5), and mostly familiar people through it (human 3)."
        ),
        strategies=[
            _s(1, "Set up their room first", "Make their space familiar early, with known bedding and items, on day one."),
            _s(2, "A countdown they can see", "Use a visual countdown to the move so it is not a surprise."),
            _s(3, "Keep key items with them", "Pack a personal bag of essentials that stays with them, not on the lorry."),
            _s(4, "Hold daily routines", "Keep mealtimes and bedtime as normal as possible through the upheaval."),
            _s(5, "Explore the new area calmly", "Walk the new neighbourhood gently in the first days to build the familiar."),
        ],
    ),
    ScenarioRow(
        chapter="family",
        activity_code="family-gathering",
        activity_name="A family gathering at home",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=2, human=4),
        rationale=(
            "A few hours of relatives (temporal 3) with the noise and busyness of a full "
            "house (sensory 4), at home so little to plan (logistical 2), but many "
            "people and social expectation (human 4)."
        ),
        strategies=[
            _s(1, "Keep a quiet room", "Set aside one room they can retreat to and let them know it is theirs."),
            _s(2, "Prepare the relatives", "Brief visitors gently on what helps and what to avoid pressing."),
            _s(3, "No forced greetings", "Agree that hugs and greetings are optional, not expected."),
            _s(4, "Plan an exit from the table", "Allow leaving the table when done rather than sitting it out."),
        ],
    ),
]


# ===========================================================================
# SOCIAL (Social & Community)
# ===========================================================================
SOCIAL_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="social",
        activity_code="birthday-party",
        activity_name="Birthday party",
        base_scores=BaseScores(temporal=3, sensory=5, logistical=3, human=4),
        rationale=(
            "A few hours of unpredictable activity (temporal 3), intense sensory input "
            "(music, games, food, lights; sensory 5), a venue to get to (logistical 3), "
            "and lots of children and social expectation (human 4)."
        ),
        strategies=[
            _s(1, "Arrive a little early", "Get there before the rush so they settle before it fills up."),
            _s(2, "Scope the quiet corner", "Find a calmer spot on arrival they can go to when it is too much."),
            _s(3, "Agree how long to stay", "Decide in advance it is fine to leave early; staying the whole time is optional."),
            _s(4, "Brief the host", "Tell the host quietly about food needs or what helps."),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="playground",
        activity_name="Playground visit",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=3),
        rationale=(
            "An open-ended but familiar outing (temporal 2), moderate outdoor "
            "stimulation (sensory 3), a known trip (logistical 2), and other children to "
            "navigate (human 3)."
        ),
        strategies=[
            _s(1, "Pick a quieter time", "Go when it is less busy, such as earlier in the day."),
            _s(2, "Name the leaving plan", "Agree before you arrive how the visit will end to ease the transition out."),
            _s(3, "Start with a known piece", "Head first for equipment they like and know."),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="restaurant-meal",
        activity_name="Restaurant meal",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=3),
        rationale=(
            "A long sit with waiting between courses (temporal 4), a busy noisy room "
            "with food smells (sensory 4), a venue to get to (logistical 3), and staff "
            "and other diners around (human 3)."
        ),
        strategies=[
            _s(1, "Check the menu first", "Look at the menu in advance so the food choice is settled, not decided on the spot."),
            _s(2, "Book a quiet table", "Ask for a booth or a corner away from the busiest area."),
            _s(3, "Bring something for the wait", "Have an activity for the gaps between ordering and food arriving."),
            _s(4, "Order early", "Ask to order quickly to shorten the hungry waiting."),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="soft-play",
        activity_name="Soft play",
        base_scores=BaseScores(temporal=3, sensory=5, logistical=2, human=3),
        rationale=(
            "An open-ended visit (temporal 3) with very high sensory load (echoing "
            "noise, colour, crowds of children; sensory 5), a familiar-enough trip "
            "(logistical 2), and many other children (human 3)."
        ),
        strategies=[
            _s(1, "Go at opening", "Arrive when it opens, before the noise and crowds build."),
            _s(2, "Ear defenders in", "Bring ear defenders for the echo and noise."),
            _s(3, "Agree a time limit", "Set a clear length of visit so it ends before it tips over."),
            _s(4, "Base yourself near the edge", "Pick a table at the quieter edge to return to."),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="swimming-pool",
        activity_name="Public swimming pool",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=4, human=3),
        rationale=(
            "A timed visit with changing either side (temporal 3), strong sensory input "
            "(echo, smell, water, cold; sensory 4), kit and changing logistics "
            "(logistical 4), and a shared public space (human 3)."
        ),
        strategies=[
            _s(1, "Quieter swim sessions", "Look for less busy or quieter-session times at the pool."),
            _s(2, "Sort changing in advance", "Plan the changing-room steps and bring easy-on kit."),
            _s(3, "Preview the smell and echo", "Mention the chlorine smell and the echo so they are expected."),
            _s(4, "Warm up gently", "Ease in at the shallow end rather than straight into the busy water."),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="club-session",
        activity_name="A club or group session",
        base_scores=BaseScores(temporal=2, sensory=3, logistical=2, human=3),
        rationale=(
            "A regular fixed-length session (temporal 2), moderate stimulation of a hall "
            "or room (sensory 3), a known trip (logistical 2), and a group with some "
            "social demand (human 3)."
        ),
        strategies=[
            _s(1, "Arrive before it starts", "Get there a few minutes early to settle before the group gathers."),
            _s(2, "Meet the leader", "Introduce them to the session leader so there is a known adult."),
            _s(3, "Know the running order", "Learn the usual shape of the session so the steps are predictable."),
            _s(4, "An opt-out for big bits", "Agree they can sit out the loudest or most exposed parts."),
        ],
    ),
    ScenarioRow(
        chapter="social",
        activity_code="cinema-trip",
        activity_name="Cinema trip",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=2, human=2),
        rationale=(
            "A film-length sit with trailers first (temporal 3), loud sound and a dark "
            "room (sensory 4), a familiar trip (logistical 2), and a low social demand "
            "in a quiet audience (human 2)."
        ),
        strategies=[
            _s(1, "Try a relaxed screening", "Look for autism-friendly or relaxed screenings with lower sound and lights up."),
            _s(2, "Sit near the exit", "Pick aisle seats near the door for an easy step-out."),
            _s(3, "Ear defenders for the volume", "Bring ear defenders for the loud trailers and big moments."),
            _s(4, "Agree leaving is fine", "Make clear that leaving partway through is allowed."),
        ],
    ),
]


# ===========================================================================
# TRAVEL (Travel & Holiday)
# ===========================================================================
TRAVEL_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="travel",
        activity_code="flight",
        activity_name="A flight",
        base_scores=BaseScores(temporal=5, sensory=5, logistical=5, human=4),
        rationale=(
            "A long day of queues, security, and waiting with unpredictable timing "
            "(temporal 5), intense and inescapable sensory input (crowds, noise, "
            "pressure; sensory 5), the heaviest logistics (airport, bags, documents; "
            "logistical 5), and many strangers and staff demands (human 4)."
        ),
        strategies=[
            _s(1, "Ask about airport assistance", "Request special assistance in advance; it can mean a quieter route and less queuing."),
            _s(2, "Walk through the journey", "Use photos or a social story of check-in, security, and boarding so each step is known."),
            _s(3, "Pack the long wait", "Bring snacks, ear defenders, chargers, and absorbing activities for the waiting."),
            _s(4, "Plan security in advance", "Explain the security check (taking shoes off, the scanner) so it is not a surprise."),
            _s(5, "A comfort kit for the air", "Have familiar items and something for ear pressure on take-off and landing."),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="long-car-journey",
        activity_name="Long car journey",
        base_scores=BaseScores(temporal=4, sensory=2, logistical=3, human=2),
        rationale=(
            "Hours confined with the boredom of duration (temporal 4) but a controllable "
            "environment (sensory 2), some planning of stops and kit (logistical 3), and "
            "only familiar people in the car (human 2)."
        ),
        strategies=[
            _s(1, "Plan the stops", "Map out break points in advance so there are known places to get out and reset."),
            _s(2, "A journey countdown", "Give a sense of how long is left with landmarks or a simple timer."),
            _s(3, "Pack the entertainment", "Have familiar audio, activities, and snacks within reach."),
            _s(4, "Keep comfort to hand", "Bring the items that help them settle in the seat."),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="train-journey",
        activity_name="Train journey",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=4, human=3),
        rationale=(
            "A journey with platform waiting and possible delays (temporal 4), a busy "
            "noisy station and carriage (sensory 4), tickets, platforms, and changes to "
            "manage (logistical 4), and shared public space (human 3)."
        ),
        strategies=[
            _s(1, "Book seats in advance", "Reserve seats, ideally in a quieter coach, so there is no scramble."),
            _s(2, "Get to the platform early", "Arrive with time so finding the platform is calm, not rushed."),
            _s(3, "Preview the station noise", "Describe the announcements and bustle so they are expected."),
            _s(4, "Have a plan for delays", "Agree what you will do if the train is late so a delay is not a crisis."),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="hotel-stay",
        activity_name="Hotel stay",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=4, human=3),
        rationale=(
            "Several nights out of routine (temporal 3) in an unfamiliar but moderate "
            "environment (sensory 3), a new place with packing and a strange room "
            "(logistical 4), and staff and other guests around (human 3)."
        ),
        strategies=[
            _s(1, "Show the room in advance", "Look at photos of the hotel and room online before you go."),
            _s(2, "Bring familiar bedding", "Pack a known pillow, blanket, or comfort item to make the room feel familiar."),
            _s(3, "Keep a routine anchor", "Hold the bedtime routine steady even in the new place."),
            _s(4, "Scope the quiet spaces", "Find the calmer areas of the hotel early so there is somewhere to retreat."),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="theme-park",
        activity_name="Theme park day",
        base_scores=BaseScores(temporal=5, sensory=5, logistical=4, human=4),
        rationale=(
            "A long day of queues and waiting (temporal 5), the most intense sensory "
            "environment (crowds, noise, rides; sensory 5), a big site to plan and "
            "navigate (logistical 4), and dense crowds of strangers (human 4)."
        ),
        strategies=[
            _s(1, "Ask about a queue pass", "Many parks offer a disability access or ride-access scheme that cuts the queuing; arrange it in advance."),
            _s(2, "Plan a few must-dos", "Pick the handful of rides that matter rather than trying to do everything."),
            _s(3, "Map the quiet spots", "Find the calmer areas in advance for breaks away from the crowds."),
            _s(4, "Pack for the day", "Bring ear defenders, snacks, water, and sun cover for the long wait."),
            _s(5, "Agree an early finish", "Decide it is fine to leave when it is enough, not at closing."),
        ],
    ),
    ScenarioRow(
        chapter="travel",
        activity_code="beach-day",
        activity_name="Beach day",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=2),
        rationale=(
            "An open-ended outing (temporal 3) with strong but natural sensory input "
            "(sand texture, sun, waves, wind; sensory 4), kit and a trip to plan "
            "(logistical 3), and an open space with low social demand (human 2)."
        ),
        strategies=[
            _s(1, "Prepare for the textures", "Mention the sand and water feel in advance, and bring shoes or a mat if texture is hard."),
            _s(2, "Set up a base", "Stake out a spot with shade and familiar items to return to."),
            _s(3, "Pick a quieter beach or time", "Choose a less crowded beach or go outside peak hours."),
            _s(4, "Plan sun and water safety", "Sort sun cover and clear water boundaries before you settle in."),
        ],
    ),
]


# ===========================================================================
# CULTURE (Culture & Faith)
# ===========================================================================
CULTURE_SCENARIOS: List[ScenarioRow] = [
    ScenarioRow(
        chapter="culture",
        activity_code="worship-service",
        activity_name="A place-of-worship service",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=2, human=3),
        rationale=(
            "A service of a set length with quiet-sitting expectations (temporal 3), "
            "moderate sensory input (music, singing, a full room; sensory 3), a familiar "
            "regular trip (logistical 2), and a community with some social expectation "
            "(human 3)."
        ),
        strategies=[
            _s(1, "Sit near the exit", "Choose seats at the back or end of a row for an easy quiet exit."),
            _s(2, "Know the order of service", "Walk through the parts of the service so the standing, singing, and quiet bits are expected."),
            _s(3, "Agree it is fine to step out", "Make clear that leaving for a few minutes during the service is allowed."),
            _s(4, "Bring a quiet activity", "Have a discreet fidget or quiet item for the longer still moments."),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="religious-festival",
        activity_name="A religious festival",
        base_scores=BaseScores(temporal=4, sensory=4, logistical=3, human=4),
        rationale=(
            "A long celebration that can run for hours (temporal 4), a busy, loud, "
            "food-and-music-filled gathering (sensory 4), some travel and preparation "
            "(logistical 3), and a large community with much social contact (human 4)."
        ),
        strategies=[
            _s(1, "Plan which parts to attend", "Pick the parts of the day that matter rather than the whole event end to end."),
            _s(2, "Prepare for the noise and food", "Mention the music, crowds, and unfamiliar foods in advance, and bring known snacks."),
            _s(3, "Keep a retreat option", "Know where a quieter space is, or plan to go home and return."),
            _s(4, "Brief the relatives", "Let family know in advance what helps so the social side is gentler."),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="wedding",
        activity_name="A wedding",
        base_scores=BaseScores(temporal=5, sensory=4, logistical=4, human=4),
        rationale=(
            "A very long day across ceremony and reception with much waiting (temporal "
            "5), a loud busy celebration (sensory 4), a new venue and formal dress to "
            "manage (logistical 4), and a crowd of mostly unfamiliar guests (human 4)."
        ),
        strategies=[
            _s(1, "Plan to attend part of it", "Decide in advance which parts to do; the whole day end to end may be too long."),
            _s(2, "Prepare a quiet escape", "Find out where a calmer room or outdoor space is for breaks."),
            _s(3, "Ease the formal clothes", "Sort comfortable formal wear ahead and let them try it on in advance."),
            _s(4, "Have a flexible exit plan", "Arrange transport so leaving early is possible without stranding anyone."),
            _s(5, "Brief a trusted adult", "Have one relative aware of what helps so support is on hand."),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="funeral",
        activity_name="A funeral",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=4),
        rationale=(
            "A service of moderate length in a charged atmosphere (temporal 3), moderate "
            "but emotionally heavy sensory input (sensory 3), an unfamiliar venue and "
            "formal expectations (logistical 3), and a gathering with high emotional and "
            "social weight (human 4)."
        ),
        strategies=[
            _s(1, "Explain simply and honestly", "Tell them plainly what a funeral is and what will happen, in words they understand."),
            _s(2, "Decide on attendance together", "Consider whether the whole service or just part is right, with no obligation to stay throughout."),
            _s(3, "Agree a quiet supporter", "Have one calm adult whose only job is to be with them and step out if needed."),
            _s(4, "Plan a gentle afterwards", "Arrange a low-key, familiar activity after to decompress."),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="community-celebration",
        activity_name="A community celebration",
        base_scores=BaseScores(temporal=3, sensory=4, logistical=3, human=4),
        rationale=(
            "A few hours of festivity (temporal 3) with crowds, music, and stalls "
            "(sensory 4), some travel and navigation (logistical 3), and a large mix of "
            "people and social contact (human 4)."
        ),
        strategies=[
            _s(1, "Arrive before the peak", "Go early before it gets busiest so they settle before the crowds build."),
            _s(2, "Scope the layout", "Find the quieter edges and the exits on arrival."),
            _s(3, "Agree a stay length", "Decide in advance how long to stay; leaving early is fine."),
            _s(4, "Bring sensory support", "Pack ear defenders and known snacks for the noise and unfamiliar food."),
        ],
    ),
    ScenarioRow(
        chapter="culture",
        activity_code="cultural-outing",
        activity_name="A museum or cultural outing",
        base_scores=BaseScores(temporal=3, sensory=3, logistical=3, human=3),
        rationale=(
            "A few hours out (temporal 3) in a moderate indoor environment (sensory 3), "
            "a new place to get to and navigate (logistical 3), and a public space with "
            "some staff and visitor contact (human 3)."
        ),
        strategies=[
            _s(1, "Plan the route inside", "Pick a couple of galleries or exhibits in advance rather than the whole place."),
            _s(2, "Check for quiet times", "Look for quieter opening times or any relaxed sessions."),
            _s(3, "Know where to rest", "Find the cafe or seating areas for breaks."),
            _s(4, "Preview with photos", "Look at the venue online beforehand so it is partly familiar."),
        ],
    ),
]


# All chapters' scenarios in one ordered list (the loader's source of truth). The
# chapter order matches app/models/chapters_v3.Chapter (School first).
ALL_SCENARIOS: List[ScenarioRow] = (
    SCHOOL_SCENARIOS
    + CAREER_SCENARIOS
    + FAMILY_SCENARIOS
    + SOCIAL_SCENARIOS
    + TRAVEL_SCENARIOS
    + CULTURE_SCENARIOS
)
