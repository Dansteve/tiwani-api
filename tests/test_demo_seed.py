"""Unit tests for the demo-seed blueprint + the safety guard (no live database).

There is no disposable Postgres here, so the actual INSERT path (scripts/seed_demo_data.py
writing through the Supabase services) is owner-run and not exercised here. What IS
verified, fully and offline:

  1. The PURE data-construction helpers (scripts/demo_data.py): the timeline maths, the
     blueprint shape, and the oldest-first ordering the seed depends on.

  2. ENGINE CONSISTENCY of the blueprint: every demo activity is folded through the REAL
     engines (app/engines/lce -> tier + strategies, app/engines/lci -> chapter score +
     trajectory, app/engines/alerts -> the Erosion Alert) exactly as the services would at
     insert time. This proves the demo data is engine-consistent (the tiers, scores, and
     the alert are the app's own, not hand-faked) and, crucially, that AT LEAST ONE Erosion
     Alert fires NATURALLY from the eroding chapter, even though the insert is owner-run.

  3. The PRODUCTION-REFUSAL guard (scripts/seed_demo_data.py): the known production host is
     refused and a demo host is accepted, and the explicit-target resolver fails closed when
     the DEMO_* connection is not fully specified. This is the brief's critical safety
     property, asserted directly.

  4. IMPORT + COMPOSE: the script and its helpers import and the blueprint composes with no
     live DB and no app settings (the structure check the brief asks for).

These tests fold the SAME sequences the script will insert, so if a future blueprint edit
breaks engine consistency or stops the alert from firing, this suite catches it before the
owner ever runs the seed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.engines.alerts import (
    ActivityPoint,
    ChapterHistory,
    PulseOutcomePoint,
    evaluate,
)
from app.engines.lce import run_engine
from app.engines.lci import (
    Outcome,
    PulsePoint,
    Snapshot,
    chapter_score,
    prior_instant,
    snapshot_score_as_of,
    trajectory,
)
from scripts import demo_data
from scripts.demo_data import ActivityStep, DemoRecipient, PulseStep
from scripts.seed_demo_data import (
    PRODUCTION_HOSTS,
    DemoTarget,
    UnsafeTargetError,
    assert_target_is_safe,
    resolve_target,
)

# A fixed evaluation instant so the windowed counts and the trajectory look-back are
# deterministic (the engines take `now`; nothing reads the wall clock).
NOW = datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# a tiny re-implementation of the service fold, OVER THE REAL ENGINES
# ---------------------------------------------------------------------------


def _fold_chapter(recipient: DemoRecipient, chapter: str):
    """Replay one chapter's history through the REAL engines, the way the services do.

    For each activity in the chapter (oldest first): run the LCE to get the recommended
    tier (the same call plans_service.prepare_plan makes), then, if the step has a pulse,
    fold the pulse into the chapter LCI (app/engines/lci.chapter_score) and record a weekly
    snapshot, exactly as pulse_service + lci_service do. Returns the engine inputs the
    alert needs plus the final score and weekly series, so a test can assert what the
    seeded account will show.
    """
    activities = [a for a in recipient.activities if a.chapter == chapter]
    activities.sort(key=lambda a: a.days_ago, reverse=True)  # oldest first

    activity_points = []
    pulse_points = []
    snapshots = []
    for step in activities:
        at = demo_data.activity_instant(NOW, step)
        result = run_engine(
            chapter=step.chapter,
            activity_code=step.activity_code,
            support_level_code=recipient.support_level_code,
            permanent_tags=list(recipient.tags),
            today_flags=list(step.today_flags),
        )
        activity_points.append(ActivityPoint(tier=result.tier, at=at))
        if step.pulse is not None:
            pulse_at = demo_data.pulse_instant(NOW, step)
            pulse_points.append(
                PulsePoint(outcome=Outcome(step.pulse.outcome_code), tier=result.tier, at=pulse_at)
            )
            score_now = chapter_score(pulse_points)
            snapshots.append(Snapshot(score=score_now, taken_at=pulse_at))

    final_score = chapter_score(pulse_points)
    weekly = [s.score for s in snapshots]
    return activity_points, pulse_points, snapshots, final_score, weekly


def _alert_level(recipient: DemoRecipient, chapter: str):
    """The Erosion Alert level the real engine returns for a chapter, evaluated at NOW."""
    activity_points, pulse_points, _snaps, final_score, weekly = _fold_chapter(recipient, chapter)
    history = ChapterHistory(
        activities=tuple(activity_points),
        pulses=tuple(PulseOutcomePoint(outcome=p.outcome, at=p.at) for p in pulse_points),
        current_lci=final_score,
        weekly_snapshot_scores=tuple(weekly),
    )
    return evaluate(history, now=NOW)


def _recipient(name: str) -> DemoRecipient:
    for r in demo_data.demo_recipients():
        if r.name.startswith(name):
            return r
    raise AssertionError(f"no demo recipient starting with {name!r}")


# ---------------------------------------------------------------------------
# 1. the pure timeline helpers
# ---------------------------------------------------------------------------


def test_activity_instant_is_now_minus_days_ago():
    step = ActivityStep(days_ago=10, chapter="family", activity_code="x")
    assert demo_data.activity_instant(NOW, step) == NOW - timedelta(days=10)


def test_activity_date_is_the_calendar_date_of_the_instant():
    step = ActivityStep(days_ago=3, chapter="family", activity_code="x")
    assert demo_data.activity_date(NOW, step) == (NOW - timedelta(days=3)).date()


def test_pulse_instant_is_a_few_hours_after_the_activity():
    step = ActivityStep(days_ago=5, chapter="family", activity_code="x", pulse=PulseStep("okay"))
    expected = (NOW - timedelta(days=5)) + timedelta(hours=demo_data.PULSE_OFFSET_HOURS)
    assert demo_data.pulse_instant(NOW, step) == expected
    # And it sorts strictly AFTER the activity, so the LCI fold sees it after the prepare.
    assert demo_data.pulse_instant(NOW, step) > demo_data.activity_instant(NOW, step)


def test_pulse_steps_are_oldest_first():
    recipient = _recipient("Amara")
    steps = demo_data.pulse_steps(recipient)
    days = [s.days_ago for s in steps]
    assert days == sorted(days, reverse=True), "pulses must fold oldest-first"
    assert all(s.pulse is not None for s in steps)


def test_all_activities_flattens_every_recipient():
    recipients = demo_data.demo_recipients()
    flat = demo_data.all_activities(recipients)
    assert len(flat) == sum(len(r.activities) for r in recipients)


# ---------------------------------------------------------------------------
# 2. the blueprint is engine-consistent (the demo data is the app's own numbers)
# ---------------------------------------------------------------------------


def test_blueprint_has_two_recipients_with_history():
    recipients = demo_data.demo_recipients()
    assert len(recipients) == 2
    for r in recipients:
        assert r.name and r.support_level_code.startswith("SL-")
        assert len(r.activities) >= 1
        assert any(a.pulse is not None for a in r.activities), "each recipient has pulses"


def test_every_demo_activity_references_a_real_seeded_scenario():
    # A custom (unseeded) code would make the engine fall back to the chapter average; the
    # demo deliberately uses only seeded scenarios so the tiers are the real matrix tiers.
    from app.seed import load_seed

    tables = load_seed()
    seeded = {(s.chapter, s.activity_code) for s in tables.scenarios}
    for step in demo_data.all_activities(demo_data.demo_recipients()):
        assert (step.chapter, step.activity_code) in seeded, (
            f"demo activity {step.chapter}/{step.activity_code} is not a seeded scenario"
        )


def test_every_pulse_outcome_and_flag_is_a_real_engine_code():
    valid_outcomes = {o.value for o in Outcome}
    for step in demo_data.all_activities(demo_data.demo_recipients()):
        if step.pulse is not None:
            assert step.pulse.outcome_code in valid_outcomes
        for flag in step.today_flags:
            # today flags are TG- codes the engine recognises (a no-op flag is harmless,
            # but a typo would silently score nothing, so pin the prefix).
            assert flag.startswith("TG-"), f"today flag {flag} is not a TG- code"


def test_amara_family_chapter_erodes_into_the_critical_band():
    # The headline natural-erosion story: Amara's FAMILY chapter (Full-tier bedtimes with
    # Difficult outcomes) declines week over week into the critical band. The score and the
    # trajectory are the REAL engine's, computed here exactly as the services would.
    amara = _recipient("Amara")
    activity_points, pulse_points, snaps, final_score, weekly = _fold_chapter(amara, "family")

    assert final_score is not None
    assert final_score < 30, f"family chapter should reach the critical band, got {final_score}"
    # The weekly series visibly declines across its most recent run (the trajectory story).
    assert weekly[0] > weekly[-1], f"family LCI should fall over time, weekly={weekly}"

    prior = snapshot_score_as_of(snaps, prior_instant(NOW))
    assert trajectory(final_score, prior).value == "under_pressure"


def test_amara_family_triggers_an_erosion_alert_naturally():
    # The brief's requirement: at least one Erosion Alert must fire NATURALLY (never planted).
    # Amara's eroding FAMILY chapter is below 30, which is the section 4.9 L3 (Critical
    # erosion) LCI branch, reached purely by folding her real pulses through the real engine.
    level = _alert_level(_recipient("Amara"), "family")
    assert level is not None, "the eroding family chapter must raise an Erosion Alert"
    assert int(level) == 3, f"expected L3 critical erosion, got {level}"


def test_theo_social_chapter_is_a_strengthening_success_story():
    # Contrast: Theo's SOCIAL chapter (Well/Okay on Pivot activities) strengthens and raises
    # NO alert, so the demo dashboard shows a positive chapter next to the eroding one.
    theo = _recipient("Theo")
    _activities, _pulses, snaps, final_score, weekly = _fold_chapter(theo, "social")
    assert final_score is not None and final_score > 50, f"social should rise, got {final_score}"
    assert weekly[-1] > weekly[0], f"social LCI should climb, weekly={weekly}"
    prior = snapshot_score_as_of(snaps, prior_instant(NOW))
    assert trajectory(final_score, prior).value == "strengthening"
    assert _alert_level(theo, "social") is None, "the success chapter must not alert"


def test_theo_school_chapter_reaches_the_early_signal_alert():
    # Theo's SCHOOL chapter reaches the natural L1 early signal (Pivot recommended in 3+
    # activities AND Difficult/Okay in 3+ pulses, both inside 30 days), a second NATURAL
    # alert from a different mechanism (the counts branch, not the LCI branch).
    level = _alert_level(_recipient("Theo"), "school")
    assert level is not None and int(level) == 1, f"expected L1 early signal, got {level}"


def test_theo_travel_chapter_is_sparse_building_picture():
    # Theo's TRAVEL chapter has a single pulse, so the LCI is real but the chapter shows the
    # section 4.8 "building your picture" sparse state (fewer than 3 pulses).
    theo = _recipient("Theo")
    _a, pulse_points, _s, final_score, _w = _fold_chapter(theo, "travel")
    assert final_score is not None
    assert len(pulse_points) < 3, "travel is meant to stay sparse for the demo"


def test_the_demo_has_at_least_one_pending_check_in():
    # The demo also shows a PENDING pulse (an activity with no outcome yet), so the in-app
    # check-in prompt has something to show. At least one activity across the blueprint has
    # no pulse.
    flat = demo_data.all_activities(demo_data.demo_recipients())
    assert any(a.pulse is None for a in flat), "expected at least one pending (un-pulsed) activity"


def test_the_demo_generates_at_least_one_continuity_card():
    cards = [a for r in demo_data.demo_recipients() for a in demo_data.card_steps(r)]
    assert len(cards) >= 1, "the demo should generate at least one Continuity Card"


# ---------------------------------------------------------------------------
# 3. the production-refusal safety guard (the brief's critical property)
# ---------------------------------------------------------------------------


def test_the_known_production_host_is_refused():
    for host in PRODUCTION_HOSTS:
        target = DemoTarget(url=f"https://{host}", anon_key="a", service_role_key="s")
        with pytest.raises(UnsafeTargetError):
            assert_target_is_safe(target)


def test_a_demo_host_is_accepted():
    target = DemoTarget(
        url="https://demo-throwaway-project.supabase.co", anon_key="a", service_role_key="s"
    )
    # Does not raise: a non-production host is allowed.
    assert_target_is_safe(target)


def test_an_unparseable_target_url_is_refused():
    target = DemoTarget(url="not-a-url", anon_key="a", service_role_key="s")
    with pytest.raises(UnsafeTargetError):
        assert_target_is_safe(target)


def test_production_host_is_refused_case_insensitively():
    host = next(iter(PRODUCTION_HOSTS)).upper()
    target = DemoTarget(url=f"https://{host}", anon_key="a", service_role_key="s")
    with pytest.raises(UnsafeTargetError):
        assert_target_is_safe(target)


def test_resolver_fails_closed_when_the_target_is_not_fully_specified(monkeypatch):
    # The explicit-target rule: with no DEMO_* env and no flags, the resolver must abort
    # rather than fall back to the app's project. SystemExit (a clean refusal) is expected.
    for var in (
        "DEMO_SUPABASE_URL",
        "DEMO_SUPABASE_KEY",
        "DEMO_SUPABASE_SERVICE_ROLE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    args = _NS(url=None, anon_key=None, service_role_key=None)
    with pytest.raises(SystemExit):
        resolve_target(args)


def test_resolver_reads_the_demo_env_when_present(monkeypatch):
    monkeypatch.setenv("DEMO_SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("DEMO_SUPABASE_KEY", "anon")
    monkeypatch.setenv("DEMO_SUPABASE_SERVICE_ROLE_KEY", "service")
    target = resolve_target(_NS(url=None, anon_key=None, service_role_key=None))
    assert target.url == "https://demo.supabase.co"
    assert target.host == "demo.supabase.co"
    assert target.anon_key == "anon" and target.service_role_key == "service"


def test_resolver_flags_override_the_env(monkeypatch):
    monkeypatch.setenv("DEMO_SUPABASE_URL", "https://from-env.supabase.co")
    monkeypatch.setenv("DEMO_SUPABASE_KEY", "env-anon")
    monkeypatch.setenv("DEMO_SUPABASE_SERVICE_ROLE_KEY", "env-service")
    target = resolve_target(
        _NS(
            url="https://from-flag.supabase.co",
            anon_key="flag-anon",
            service_role_key="flag-service",
        )
    )
    assert target.url == "https://from-flag.supabase.co"
    assert target.anon_key == "flag-anon"


# ---------------------------------------------------------------------------
# 4. import + compose without a live DB (the structure check)
# ---------------------------------------------------------------------------


def test_the_script_and_blueprint_import_and_compose_without_a_database():
    # Importing the seed script must not open a connection or read the app's settings; the
    # blueprint must compose to plain data. (If either touched a DB at import, this suite
    # could not have imported it at the top of the file.)
    import scripts.seed_demo_data as seed_module

    assert hasattr(seed_module, "main")
    recipients = demo_data.demo_recipients()
    assert recipients and all(isinstance(r, DemoRecipient) for r in recipients)


def test_the_demo_email_is_a_clearly_fake_example_address():
    # No real PII: the demo Coordinator email must be on a reserved example domain so it can
    # never collide with a real person.
    assert demo_data.DEMO_COORDINATOR_EMAIL.endswith("@example.com")


class _NS:
    """A tiny argparse.Namespace stand-in for the resolver tests."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
