"""Table-driven tests for the Erosion Alert ENGINE (Product.md section 4.9).

The engine (app/engines/alerts/evaluation.py) is a PURE function over one chapter's
history: (activities, pulses, current LCI, weekly snapshots) + an evaluation instant
-> the active level (or None). These tests drive each section 4.9 threshold to its
boundary and pin the exact level, including:

  - L1 at the 3-and-3 boundary (and just under it);
  - L2 via the >= 5-in-30-days counts AND, separately, the 3-weekly-decline branch;
  - L3 via the 14-day Pivot+Difficult counts AND, separately, chapter LCI < 30;
  - higher replaces lower (a history meeting L3 reports L3, not L1);
  - the window edges (a point just outside 30/14 days does not count);
  - the governed copy substitution and the action labels (verbatim, section 4.9);
  - the per-chapter signposts are community/statutory only.

The dismissal "returns only on worsening" behaviour is a SERVICE concern (it persists
the dismissed level) and is pinned in tests/test_alerts_routes.py. The prohibited-words
guard over ALL emitted copy is tests/test_engine_alerts_guard.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.engines.alerts import (
    ActivityPoint,
    AlertLevel,
    ChapterHistory,
    PulseOutcomePoint,
    action_label_for,
    render_alert,
    render_prompt,
    signposts_for,
)
from app.engines.alerts.evaluation import _lci_declining
from app.engines.lci import Outcome
from app.models.chapters import Chapter
from app.models.seed import Tier

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _days_ago(n: float) -> datetime:
    """An instant n days before NOW (a float allows 'just inside/outside' edges)."""
    return NOW - timedelta(days=n)


def _activities(tier: Tier, count: int, *, days_ago: float = 1.0) -> list[ActivityPoint]:
    """`count` activities of one tier, all `days_ago` days before NOW."""
    return [ActivityPoint(tier=tier, at=_days_ago(days_ago)) for _ in range(count)]


def _pulses(outcome: Outcome, count: int, *, days_ago: float = 1.0) -> list[PulseOutcomePoint]:
    """`count` pulses of one outcome, all `days_ago` days before NOW."""
    return [PulseOutcomePoint(outcome=outcome, at=_days_ago(days_ago)) for _ in range(count)]


# ---------------------------------------------------------------------------
# the empty / no-pressure baseline
# ---------------------------------------------------------------------------


def test_no_history_is_no_alert():
    from app.engines.alerts import evaluate

    assert evaluate(ChapterHistory(), now=NOW) is None


def test_well_outcomes_and_full_activities_never_alert():
    # Full-engagement activities and Well pulses are NOT pressure signals; even many
    # of them raise nothing.
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.FULL, 10),
        pulses=_pulses(Outcome.WELL, 10),
        current_lci=80,
    )
    assert evaluate(history, now=NOW) is None


# ---------------------------------------------------------------------------
# L1: Modified/Pivot in >= 3 activities (30d) AND Difficult/Okay in >= 3 pulses (30d)
# ---------------------------------------------------------------------------


def test_l1_fires_at_the_three_and_three_boundary():
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 3, days_ago=5),
        pulses=_pulses(Outcome.OKAY, 3, days_ago=5),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L1


def test_l1_does_not_fire_with_only_two_activities():
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 2, days_ago=5),
        pulses=_pulses(Outcome.OKAY, 3, days_ago=5),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is None


def test_l1_does_not_fire_with_only_two_pressure_pulses():
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 3, days_ago=5),
        pulses=_pulses(Outcome.DIFFICULT, 2, days_ago=5),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is None


def test_l1_counts_modified_activities_and_difficult_pulses():
    # The L1 tier set is Modified OR Pivot; the L1 outcome set is Difficult OR Okay.
    # Modified activities + Difficult pulses meet L1 but NOT L3 (which needs Pivot),
    # and with a healthy LCI it is exactly L1 (not L2: only 3 of each, not 5).
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 3, days_ago=10),
        pulses=_pulses(Outcome.DIFFICULT, 3, days_ago=10),
        current_lci=45,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L1


def test_l1_ignores_activities_older_than_30_days():
    # An activity 31 days old is outside the 30-day window and does not count, so the
    # 3-activity threshold is not met.
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=(
            _activities(Tier.MODIFIED, 2, days_ago=5)
            + _activities(Tier.MODIFIED, 1, days_ago=31)
        ),
        pulses=_pulses(Outcome.OKAY, 3, days_ago=5),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is None


# ---------------------------------------------------------------------------
# L2 branch A: the L1 thresholds at >= 5 in 30 days
# ---------------------------------------------------------------------------


def test_l2_fires_at_the_five_and_five_counts_boundary():
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 5, days_ago=10),
        pulses=_pulses(Outcome.OKAY, 5, days_ago=10),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L2


def test_four_and_four_is_still_only_l1():
    # Four pressure activities + four pressure pulses meet L1 (>= 3) but not L2 (>= 5).
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 4, days_ago=10),
        pulses=_pulses(Outcome.OKAY, 4, days_ago=10),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L1


# ---------------------------------------------------------------------------
# L2 branch B: the chapter LCI declining for 3 weekly snapshots in a row
# ---------------------------------------------------------------------------


def test_l2_fires_on_three_weekly_declines_even_without_the_counts():
    # No pressure activities/pulses, but the weekly LCI fell across three weeks
    # (four points strictly decreasing): 60 > 55 > 48 > 40.
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=(),
        pulses=(),
        current_lci=40,
        weekly_snapshot_scores=(60, 55, 48, 40),
    )
    assert evaluate(history, now=NOW) is AlertLevel.L2


def test_lci_decline_needs_three_consecutive_drops():
    # Three weekly points (two drops) is not yet "declining for 3 weekly snapshots".
    assert _lci_declining((60, 55, 48)) is False
    # Four strictly-decreasing points (three drops) is.
    assert _lci_declining((60, 55, 48, 40)) is True
    # A blip up breaks the run (only the most recent four are tested).
    assert _lci_declining((60, 55, 58, 50)) is False
    # Equal points are not a decline (strict).
    assert _lci_declining((50, 50, 50, 50)) is False


def test_lci_decline_uses_only_the_most_recent_four_weeks():
    # An older recovering run does not matter; the last four are the live run.
    assert _lci_declining((30, 80, 70, 60, 50)) is True


# ---------------------------------------------------------------------------
# L3 branch A: Pivot in >= 3 activities (14d) AND Difficult in >= 3 pulses (14d)
# ---------------------------------------------------------------------------


def test_l3_fires_on_three_pivot_and_three_difficult_in_14_days():
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.PIVOT, 3, days_ago=7),
        pulses=_pulses(Outcome.DIFFICULT, 3, days_ago=7),
        current_lci=50,  # not below 30, so this is purely the counts branch
    )
    assert evaluate(history, now=NOW) is AlertLevel.L3


def test_l3_counts_require_pivot_not_just_modified():
    # Modified activities do NOT count for L3 (only Pivot does). Three Modified +
    # three Difficult meets L1/L2-counts shape but not the L3 counts branch, and the
    # LCI is healthy, so it is not L3. (It is L1: 3 Modified + 3 Difficult in 30d.)
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 3, days_ago=7),
        pulses=_pulses(Outcome.DIFFICULT, 3, days_ago=7),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L1


def test_l3_counts_require_difficult_not_okay():
    # Okay pulses do NOT count for L3 (only Difficult does). Three Pivot + three Okay
    # is not the L3 counts branch; with a healthy LCI it falls back to L1.
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.PIVOT, 3, days_ago=7),
        pulses=_pulses(Outcome.OKAY, 3, days_ago=7),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L1


def test_l3_counts_respect_the_14_day_window():
    # Pivot activities 15 days old are outside the 14-day L3 window. Three Difficult
    # pulses are recent, but only 2 Pivot activities are inside 14 days, so the L3
    # counts branch is not met; with a healthy LCI it is L1 (the 30-day window still
    # sees 3 Pivot + 3 Difficult).
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=(
            _activities(Tier.PIVOT, 2, days_ago=7)
            + _activities(Tier.PIVOT, 1, days_ago=15)
        ),
        pulses=_pulses(Outcome.DIFFICULT, 3, days_ago=7),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L1


# ---------------------------------------------------------------------------
# L3 branch B: chapter LCI below 30
# ---------------------------------------------------------------------------


def test_l3_fires_when_lci_is_below_30_with_no_counts():
    from app.engines.alerts import evaluate

    history = ChapterHistory(activities=(), pulses=(), current_lci=29)
    assert evaluate(history, now=NOW) is AlertLevel.L3


def test_lci_exactly_30_is_not_l3():
    # "below 30" is strict: 30 itself is not critical.
    from app.engines.alerts import evaluate

    history = ChapterHistory(activities=(), pulses=(), current_lci=30)
    assert evaluate(history, now=NOW) is None


def test_none_lci_is_not_l3():
    # A chapter with no pulse (None score) cannot be "below 30".
    from app.engines.alerts import evaluate

    history = ChapterHistory(activities=(), pulses=(), current_lci=None)
    assert evaluate(history, now=NOW) is None


# ---------------------------------------------------------------------------
# higher replaces lower
# ---------------------------------------------------------------------------


def test_l3_replaces_l2_and_l1_when_all_conditions_are_met():
    # This history meets L1 (3+ Modified/Pivot + 3+ Difficult/Okay in 30d), L2 (5+ of
    # each, AND a 3-week decline), AND L3 (3 Pivot + 3 Difficult in 14d, AND LCI < 30).
    # evaluate() must report the HIGHEST: L3.
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.PIVOT, 6, days_ago=7),
        pulses=_pulses(Outcome.DIFFICULT, 6, days_ago=7),
        current_lci=25,
        weekly_snapshot_scores=(60, 50, 40, 25),
    )
    assert evaluate(history, now=NOW) is AlertLevel.L3


def test_l2_replaces_l1_when_both_are_met():
    # 5 + 5 counts meet both L1 and L2; the result is L2 (the higher).
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.MODIFIED, 5, days_ago=10),
        pulses=_pulses(Outcome.DIFFICULT, 5, days_ago=10),
        current_lci=50,
    )
    assert evaluate(history, now=NOW) is AlertLevel.L2


def test_alert_levels_order_naturally():
    # The IntEnum ordering underpins higher-replaces-lower and worsen-past-threshold.
    assert AlertLevel.L3 > AlertLevel.L2 > AlertLevel.L1
    assert int(AlertLevel.L1) == 1 and int(AlertLevel.L2) == 2 and int(AlertLevel.L3) == 3


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_evaluate_is_pure_and_deterministic():
    from app.engines.alerts import evaluate

    history = ChapterHistory(
        activities=_activities(Tier.PIVOT, 3, days_ago=7),
        pulses=_pulses(Outcome.DIFFICULT, 3, days_ago=7),
        current_lci=40,
    )
    first = evaluate(history, now=NOW)
    second = evaluate(history, now=NOW)
    assert first is second is AlertLevel.L3


# ---------------------------------------------------------------------------
# the governed copy (verbatim section 4.9) + signposts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected_label",
    [
        (AlertLevel.L1, "Review support options"),
        (AlertLevel.L2, "See suggestions"),
        (AlertLevel.L3, "Find support"),
    ],
)
def test_action_labels_are_the_verbatim_section_4_9_ctas(level, expected_label):
    assert action_label_for(level) == expected_label


def test_l1_prompt_is_verbatim_with_the_chapter_name_substituted():
    prompt = render_prompt(Chapter.CAREER, AlertLevel.L1)
    assert prompt == (
        "Your Career chapter has been under some pressure recently. "
        "This is worth paying attention to before it builds. "
        "Would you like to review your support structure?"
    )


def test_l2_prompt_is_verbatim_with_the_chapter_name_substituted():
    prompt = render_prompt(Chapter.SCHOOL, AlertLevel.L2)
    assert prompt == (
        "Something to pay attention to. Your School chapter has been under "
        "sustained pressure for a few weeks. TIWANI noticed. Here are some things "
        "that might help."
    )


def test_l3_prompt_is_verbatim_with_the_chapter_name_substituted():
    prompt = render_prompt(Chapter.FAMILY, AlertLevel.L3)
    assert prompt == (
        "Your Family Life & Routine continuity needs attention. TIWANI has noticed a "
        "pattern of significant disruption. This is exactly what TIWANI is designed "
        "to help with. You do not have to manage this alone."
    )


def test_prompt_substitutes_only_the_chapter_token():
    # The [chapter] token is replaced; no other token remains.
    prompt = render_prompt(Chapter.TRAVEL, AlertLevel.L1)
    assert "[chapter]" not in prompt
    assert "Travel & Holiday" in prompt


def test_render_alert_assembles_the_full_governed_view():
    copy = render_alert(Chapter.CAREER, AlertLevel.L3)
    assert copy.chapter is Chapter.CAREER
    assert copy.level is AlertLevel.L3
    assert copy.action_label == "Find support"
    assert "Career continuity needs attention" in copy.prompt
    assert len(copy.signposts) >= 1


def test_every_chapter_has_at_least_one_signpost():
    for chapter in Chapter:
        assert len(signposts_for(chapter)) >= 1


def test_career_signposts_lead_with_workplace_support():
    labels = [s.label for s in signposts_for(Chapter.CAREER)]
    assert any("Carers UK" in label for label in labels)
    assert any("ACAS" in label for label in labels)


def test_school_signposts_lead_with_send_statutory_bodies():
    labels = [s.label for s in signposts_for(Chapter.SCHOOL)]
    assert any("IPSEA" in label for label in labels)
    assert any("SENDIASS" in label for label in labels)
