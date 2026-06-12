"""The demo blueprint: pure, DB-free data-construction helpers for the seed script.

This module holds WHAT the demo seeds, as plain data plus pure functions, separated
from HOW it is inserted (scripts/seed_demo_data.py does the Supabase writes). Keeping
the composition pure means the realistic activity/pulse sequences can be unit-tested
(tests/test_demo_seed.py) without a live database: the test builds the same timeline
this module describes and folds it through the REAL engines (app/engines/lce,
app/engines/lci, app/engines/alerts) to prove the demo is engine-consistent and that
the erosion alert fires NATURALLY, even though the actual insert is owner-run.

Design (verified against the real engines before it was written):

  Two demo care recipients under one demo Coordinator, each with a believable
  six-week, six-chapter history. Every score, tier, strategy, LCI value, trajectory,
  and alert is produced by the real engines and services at insert time; nothing here
  hand-fakes a score. This module only chooses the INPUTS (which seeded activity, what
  support level + tags, which pulse outcome, on which day), which is exactly what a
  real Coordinator would have entered.

  Recipient A, "Amara" (LOW support, light sensory tag): her FAMILY chapter ERODES.
  The seeded family bedtime scenario scores Full Engagement at LOW support, and a
  run of Difficult bedtimes (Full + Difficult = the -8 cell, section 4.8) drives the
  chapter LCI down week over week into the critical band, so an Erosion Alert fires
  NATURALLY (no alert is ever planted). Her other chapters carry a calmer mix.

  Recipient B, "Theo" (HIGH support, sensory + transition tags): his SOCIAL chapter is
  a success story (mostly Well/Okay on Continuity Pivot activities, a rising LCI and a
  strengthening trajectory, no alert), his SCHOOL chapter shows early pressure (the
  natural L1 from Pivot activities with Difficult/Okay pulses), and his TRAVEL chapter
  is sparse (one pulse, the "building your picture" state).

The timeline is anchored to a "days ago" offset per entry so the weekly LCI snapshots
and the 30-day / 14-day alert windows are real once the rows are backdated to those
instants (the script backdates created_at / taken_at to match). NEWEST entries are
last in each sequence.

No em or en dashes anywhere (root CLAUDE.md writing convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Sequence

# ---------------------------------------------------------------------------
# the demo identities (recognisable demo names + a clearly-demo email; NO real PII)
# ---------------------------------------------------------------------------

# A clearly-fictional demo Coordinator. The email uses the reserved example.com domain
# (RFC 2606) and a "tiwani-demo" local part so it can never collide with a real user and
# reads unmistakably as demo data. The password is a fixed demo credential the owner can
# sign in with to drive the populated account; it is intentionally not a secret.
DEMO_COORDINATOR_FIRST_NAME = "Demo Coordinator"
DEMO_COORDINATOR_EMAIL = "tiwani-demo.coordinator@example.com"
DEMO_COORDINATOR_PASSWORD = "tiwani-demo-account-2026"

# A stable tag the script writes on every demo row's owning profile is not possible
# (the schema has no marker column), so idempotency keys on the demo email instead:
# the script finds-or-creates the one auth user with this email and clears that user's
# prior demo rows before reseeding (see scripts/seed_demo_data.py).


# ---------------------------------------------------------------------------
# the pure timeline primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PulseStep:
    """One post-activity Pulse to record for an activity.

    outcome_code is an app/engines/lci Outcome value ("well" / "okay" / "difficult" /
    "skipped"). challenge_dimension is the optional "main challenge" the second Pulse
    question captures (a Dimension value), stored but never scored. The Pulse instant is
    derived from its activity's day (the activity day + a few hours), so it always lands
    just after the activity it belongs to.
    """

    outcome_code: str
    challenge_dimension: str | None = None


@dataclass(frozen=True)
class ActivityStep:
    """One prepared activity in the demo history, with its Pulse (if any).

    days_ago is how many days before "now" the activity was prepared (so the script can
    backdate it onto a real six-week timeline). chapter + activity_code select a SEEDED
    scenario (so the engine scores it from real data; a custom code would fall back to the
    chapter average, which the demo avoids). today_flags are optional TG- "today" flags
    the request carries (the engine applies them; the demo uses them sparingly so a couple
    of days read as harder). pulse is the outcome to record, or None for an activity that
    has no Pulse yet (so the demo also shows a "pending check-in"). make_card is True for
    the one or two activities a Continuity Card is generated from.
    """

    days_ago: int
    chapter: str
    activity_code: str
    today_flags: Sequence[str] = field(default_factory=tuple)
    pulse: PulseStep | None = None
    make_card: bool = False


@dataclass(frozen=True)
class DemoRecipient:
    """One demo care recipient and the full activity/pulse history to seed for them.

    name is the recipient's display name (the card shows the FIRST name only). The
    support_level_code (SL-LOW / SL-MED / SL-HIGH) and the permanent tags drive the LCE
    scoring exactly as a real profile would, so the tiers the history produces are the
    engine's, not chosen here. activities is the ordered history (newest last).
    """

    name: str
    age_band: str
    support_level_code: str
    tags: Sequence[str]
    activities: Sequence[ActivityStep]


# ---------------------------------------------------------------------------
# the blueprint (the two recipients, verified engine-consistent before writing)
# ---------------------------------------------------------------------------


def _amara() -> DemoRecipient:
    """Recipient A: a LOW-support child whose FAMILY chapter erodes naturally.

    LOW support with only zero-uplift permanent tags (a verbal child, short recovery)
    keeps the seeded bedtime scenario at Full Engagement, so the run of Difficult bedtimes
    lands on the -8 cell and the chapter LCI falls week over week into the critical band (a
    natural Erosion Alert). A score-adding tag (sensory / transition) would lift bedtime to
    Modified, where Difficult is 0 and nothing erodes, so Amara's tags are deliberately the
    non-scoring families. The School and Travel chapters carry a calmer, mixed history so
    the dashboard is not uniformly red.
    """
    family_bedtime = "bedtime-routine-typical-evening"  # Full at SL-LOW (sums to 8)
    activities: List[ActivityStep] = [
        # FAMILY: a six-week bedtime story that erodes (newest last). Full + Difficult is
        # the -8 cell, so the chapter LCI declines toward the critical band naturally. The
        # bedtimes carry NO today-flag: a flag like TG-FATIGUE would lift the tier to
        # Modified (Difficult 0) and stop the erosion, so the recurring struggle is plain.
        ActivityStep(45, "family", family_bedtime, pulse=PulseStep("well")),
        ActivityStep(38, "family", family_bedtime, pulse=PulseStep("okay")),
        ActivityStep(31, "family", family_bedtime, pulse=PulseStep("difficult", "sensory")),
        ActivityStep(24, "family", family_bedtime, pulse=PulseStep("difficult", "human")),
        ActivityStep(17, "family", family_bedtime, pulse=PulseStep("difficult", "sensory")),
        ActivityStep(10, "family", family_bedtime, pulse=PulseStep("difficult", "temporal")),
        ActivityStep(
            3,
            "family",
            family_bedtime,
            pulse=PulseStep("difficult", "human"),
            make_card=True,
        ),
        # SCHOOL: a steadier mix (Modified at LOW support) with mostly Okay/Well, so this
        # chapter reads calmer than Family and the dashboard shows contrast.
        ActivityStep(28, "school", "school-gate-drop-off-routine", pulse=PulseStep("okay")),
        ActivityStep(
            14, "school", "parent-school-meeting-routine-review", pulse=PulseStep("well")
        ),
        # TRAVEL: one recent, still-pending activity (no Pulse), so the demo shows a
        # pending check-in prompt as well as completed history.
        ActivityStep(
            2, "travel", "car-journey-short-familiar-route-under-1-hour", pulse=None
        ),
    ]
    return DemoRecipient(
        name="Amara Bello",
        age_band="6-8",
        support_level_code="SL-LOW",
        # Zero-uplift tags only (the communication + short-recovery families add no
        # dimension score), so the Full-tier bedtime stays Full and the chapter erodes.
        tags=("CM-VERBAL", "RC-SHORT"),
        activities=activities,
    )


def _theo() -> DemoRecipient:
    """Recipient B: HIGH support, with a success chapter, an early-pressure one, and a sparse one.

    HIGH support + sensory/transition tags lifts most activities to Continuity Pivot. On
    Pivot, Well is +5 and Okay is +3 (both positive) while Difficult is +2 (the plan
    protected the day), so his SOCIAL chapter strengthens. His SCHOOL chapter reaches the
    natural L1 early-signal (Pivot recommended in 3+ activities AND Difficult/Okay in 3+
    pulses, both inside 30 days). His TRAVEL chapter has a single pulse (the sparse
    "building your picture" state).
    """
    activities: List[ActivityStep] = [
        # SOCIAL: a success story, mostly Well/Okay on Pivot activities (rising LCI).
        ActivityStep(
            30, "social", "playdate-familiar-child-home-setting", pulse=PulseStep("well")
        ),
        ActivityStep(
            22, "social", "family-gathering-small-familiar-group", pulse=PulseStep("okay")
        ),
        ActivityStep(
            12,
            "social",
            "eating-out-familiar-restaurant",
            pulse=PulseStep("well"),
            make_card=True,
        ),
        ActivityStep(
            4, "social", "public-transport-routine-journey", pulse=PulseStep("okay")
        ),
        # SCHOOL: early pressure. Pivot activities + Difficult/Okay pulses inside 30 days
        # reach the natural L1 early signal. (The LCI stays positive because Difficult on
        # Pivot is +2; the alert here is driven by the activity/pulse COUNTS, section 4.9.)
        ActivityStep(
            26,
            "school",
            "playground-arrival-open-unstructured-time",
            pulse=PulseStep("difficult", "sensory"),
        ),
        ActivityStep(
            18,
            "school",
            "lesson-transitions-between-classes-or-spaces",
            pulse=PulseStep("okay", "logistical"),
        ),
        ActivityStep(
            9,
            "school",
            "breaktime-and-lunchtime",
            today_flags=("TG-ANXIETY",),
            pulse=PulseStep("difficult", "sensory"),
        ),
        # TRAVEL: a single pulse so the chapter is sparse (the "building your picture" label).
        ActivityStep(
            6,
            "travel",
            "train-journey-short-familiar",
            pulse=PulseStep("okay", "temporal"),
        ),
    ]
    return DemoRecipient(
        name="Theo Okafor",
        age_band="9-11",
        support_level_code="SL-HIGH",
        tags=("SN-NOISE", "SN-CROWD", "TR-CHANGE", "CM-MIXED", "RC-EXT"),
        activities=activities,
    )


def demo_recipients() -> List[DemoRecipient]:
    """The full demo blueprint: the two care recipients and their histories, newest pulse last.

    Pure (no DB, no clock): the seed script iterates this to drive the real plan / pulse /
    card services, and the unit tests iterate the SAME structure to fold it through the
    real engines and assert the demo is engine-consistent (and that an alert fires).
    """
    return [_amara(), _theo()]


# ---------------------------------------------------------------------------
# pure timeline helpers (turn a "days ago" offset into concrete instants)
# ---------------------------------------------------------------------------

# A Pulse is recorded a few hours after its activity (so it always sorts AFTER the
# activity in the LCI fold and falls in the same day's window). This mirrors the plan
# service's own Pulse scheduling shape (the activity time + a couple of hours) without
# importing it, so the helpers stay pure.
PULSE_OFFSET_HOURS = 3


def activity_instant(now: datetime, step: ActivityStep) -> datetime:
    """The instant an activity was prepared: `now` minus its days_ago offset.

    Used to backdate activity_record.created_at and to set the activity date the plan
    service schedules the Pulse from, so the six-week history is real (not all "today").
    """
    return now - timedelta(days=step.days_ago)


def activity_date(now: datetime, step: ActivityStep) -> date:
    """The calendar date of an activity (the date the plan service schedules the Pulse off)."""
    return activity_instant(now, step).date()


def pulse_instant(now: datetime, step: ActivityStep) -> datetime:
    """The instant a Pulse was recorded: a few hours after its activity.

    Backdates pulse_record.created_at and the lci_snapshot.taken_at so the weekly
    trajectory and the alert windows see a genuine timeline. Only meaningful when the
    step HAS a pulse.
    """
    return activity_instant(now, step) + timedelta(hours=PULSE_OFFSET_HOURS)


def all_activities(recipients: Sequence[DemoRecipient]) -> List[ActivityStep]:
    """Every ActivityStep across all recipients (a flat list, for counts and tests)."""
    out: List[ActivityStep] = []
    for r in recipients:
        out.extend(r.activities)
    return out


def pulse_steps(recipient: DemoRecipient) -> List[ActivityStep]:
    """The recipient's activities that HAVE a Pulse, ordered oldest-first (the fold order).

    Oldest-first is the order the LCI must fold and the order the script records pulses
    in, so each backdated snapshot captures the score as of that week.
    """
    pulsed = [a for a in recipient.activities if a.pulse is not None]
    return sorted(pulsed, key=lambda a: a.days_ago, reverse=True)


def card_steps(recipient: DemoRecipient) -> List[ActivityStep]:
    """The recipient's activities a Continuity Card should be generated from."""
    return [a for a in recipient.activities if a.make_card]
