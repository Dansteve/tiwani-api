#!/usr/bin/env python3
"""Seed a realistic, populated demo account into a DEMO / throwaway Supabase project.

WHAT IT IS FOR. The beta needs a believable, populated account to demo: a Coordinator
with a couple of care recipients and a six-week, six-chapter history (prepared plans,
post-activity pulses with mixed outcomes, a natural Erosion Alert, and a Continuity Card
or two). This script builds exactly that, driving the REAL services and engines so the
demo data is engine-consistent (the LCI scores, tiers, strategies, trajectories, and the
alert are all computed by the app, never hand-faked here).

  >>> CRITICAL SAFETY (read before running) <<<

  This script WRITES rows. It is meant to be run by the OWNER against a DEMO or
  THROWAWAY Supabase project, NEVER against production. Two guards enforce that:

    1. It takes its target connection EXPLICITLY. It reads the target from
       DEMO_SUPABASE_URL / DEMO_SUPABASE_KEY / DEMO_SUPABASE_SERVICE_ROLE_KEY (or the
       matching --url / --anon-key / --service-role-key flags). It deliberately does NOT
       fall back to the app's own SUPABASE_URL / .env, so you cannot seed the live
       project by accident just because your shell has the app's env loaded.

    2. It HARD-REFUSES the known production host. The production Supabase host is pinned
       in PRODUCTION_HOSTS below; if the target URL resolves to it, the script aborts
       before any write. This mirrors the prod-refusal posture of the real-Postgres RLS
       test (tests/test_rls_isolation.py), which only ever runs against an explicit,
       non-production database. Add hosts to PRODUCTION_HOSTS if production moves.

  The target project must already have the public migrations applied (the v3 tables and
  their RLS policies, supabase/migrations/), and Auth enabled, so the demo Coordinator
  can be created and signed in.

HOW THE DEMO DATA IS BUILT (engine-consistent, not hand-faked):
  - The demo Coordinator is created through Supabase Auth (auth.admin.create_user, the
    service-role admin path, the same identity store the real app uses), then SIGNED IN
    on the anon client to obtain a real access token. Every subsequent write runs as that
    signed-in user through get_anon_client(token), so Row Level Security applies exactly
    as it does for a real request (no service-role shortcut for user data).
  - Each care recipient is created via the profile service; each activity is prepared via
    the plan service (which RUNS the LCE and stores the activity_record + strategies);
    each Pulse is recorded via the pulse service (which RECOMPUTES the LCI, snapshots it,
    and EVALUATES the Erosion Alert). The script supplies the past instant for each step,
    and backdates the rows' created_at / taken_at so the six-week timeline (and therefore
    the weekly trajectory and the 30 / 14-day alert windows) is genuine.
  - The blueprint (which seeded activities, what outcomes, on which days) lives in
    scripts/demo_data.py and is unit-tested (tests/test_demo_seed.py) by folding the same
    sequences through the real engines, so the natural alert is verified there too.

IDEMPOTENCY. Re-running is safe: the script finds-or-creates the one demo Auth user by
its fixed demo email and, before reseeding, deletes that user's prior demo rows
(card_record, lci_snapshot, pulse_record, activity_record, child_profile) under that
user's own RLS session. It never touches any other user's data.

USAGE. See scripts/README.md, or run with --help. Nothing here imports at module load
that opens a connection; the Supabase calls happen only inside main().
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence
from urllib.parse import urlparse

# Allow running BOTH as `python -m scripts.seed_demo_data` (repo root already on the path)
# AND as `python scripts/seed_demo_data.py` (the script's directory is on the path, not the
# repo root). In the latter case `import scripts...` / `import app...` would fail, so put the
# repo root (this file's parent's parent) at the front of sys.path. Idempotent.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# the production-refusal guard (mirrors the RLS test's explicit-target posture)
# ---------------------------------------------------------------------------

# The known production Supabase host(s). If the target URL resolves to any of these, the
# script aborts before writing a single row. This is the hard refusal the brief requires:
# the live data is never seeded with demo rows. If production ever moves, add the new host
# here (and keep the old one, so a stale config is still refused).
PRODUCTION_HOSTS = frozenset(
    {
        "kogpfmuxgfjfjkdwrsjv.supabase.co",
    }
)


class UnsafeTargetError(RuntimeError):
    """Raised when the resolved target is (or looks like) production. The script aborts."""


@dataclass(frozen=True)
class DemoTarget:
    """The explicitly-provided demo connection the script will write to.

    All three are required: the anon key drives the RLS-scoped user writes, the
    service-role key creates and (on a reseed) removes the demo Auth user. They come from
    the DEMO_* env vars or the matching flags, NEVER from the app's own SUPABASE_* / .env,
    so the live project cannot be hit just because the app env is loaded.
    """

    url: str
    anon_key: str
    service_role_key: str

    @property
    def host(self) -> str:
        return (urlparse(self.url).hostname or "").lower()


def resolve_target(args: argparse.Namespace) -> DemoTarget:
    """Read the demo connection from the flags or the DEMO_* env vars (flags win).

    Deliberately separate from app.config.settings: the app reads SUPABASE_* (production);
    this reads DEMO_* so the two can never be confused. Missing any of the three is a
    hard error with a clear message (we do not silently fall back to the app's project).
    """
    url = args.url or os.environ.get("DEMO_SUPABASE_URL", "")
    anon_key = args.anon_key or os.environ.get("DEMO_SUPABASE_KEY", "")
    service_role_key = args.service_role_key or os.environ.get(
        "DEMO_SUPABASE_SERVICE_ROLE_KEY", ""
    )

    missing = [
        name
        for name, value in (
            ("DEMO_SUPABASE_URL (or --url)", url),
            ("DEMO_SUPABASE_KEY (or --anon-key)", anon_key),
            ("DEMO_SUPABASE_SERVICE_ROLE_KEY (or --service-role-key)", service_role_key),
        )
        if not value.strip()
    ]
    if missing:
        raise SystemExit(
            "Refusing to run: the demo target is not fully specified. Missing:\n  - "
            + "\n  - ".join(missing)
            + "\n\nProvide them explicitly (these are intentionally NOT read from the "
            "app's SUPABASE_* / .env, so you cannot seed production by accident). "
            "See scripts/README.md."
        )

    return DemoTarget(
        url=url.strip(),
        anon_key=anon_key.strip(),
        service_role_key=service_role_key.strip(),
    )


def assert_target_is_safe(target: DemoTarget) -> None:
    """Hard-refuse a production target. Called BEFORE any client is built or row written.

    The refusal is on the URL host: if it matches a pinned production host the script
    aborts. An empty / unparseable host is also refused (we only ever write to a host we
    can read and confirm is not production).
    """
    host = target.host
    if not host:
        raise UnsafeTargetError(
            f"Refusing to run: could not parse a host from the target URL '{target.url}'. "
            "Point DEMO_SUPABASE_URL at a real demo project URL."
        )
    if host in PRODUCTION_HOSTS:
        raise UnsafeTargetError(
            f"REFUSING TO RUN against the known production host '{host}'. "
            "This script seeds demo data and must only ever target a demo / throwaway "
            "project. If production has genuinely moved, update PRODUCTION_HOSTS in "
            "scripts/seed_demo_data.py (keep the old host listed)."
        )


# ---------------------------------------------------------------------------
# the seed run (imports the app lazily, AFTER the safety guard has passed)
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse args, enforce the safety guard, then seed the demo account. Returns an exit code."""
    args = _build_parser().parse_args(argv)

    target = resolve_target(args)
    try:
        assert_target_is_safe(target)
    except UnsafeTargetError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Demo seed target: {target.url} (host {target.host})")
    if args.dry_run:
        print(
            "Dry run: the target is accepted (not production) and the blueprint composes. "
            "No rows were written. Drop --dry-run to seed."
        )
        # Compose the blueprint to prove it imports and builds without a live DB.
        from scripts.demo_data import demo_recipients

        recipients = demo_recipients()
        total_activities = sum(len(r.activities) for r in recipients)
        print(
            f"Would seed {len(recipients)} care recipients and {total_activities} activities "
            f"under {_coordinator_email()}."
        )
        return 0

    # Point the app's clients at the DEMO project BEFORE importing anything that reads
    # settings, so app.db builds its clients against the demo URL (never the app's own).
    _apply_demo_env(target)

    # Imported here, after the env is set and the guard has passed, so importing this
    # module never constructs a client or reads the app's production settings.
    from scripts.demo_data import (
        DEMO_COORDINATOR_EMAIL,
        DEMO_COORDINATOR_FIRST_NAME,
        DEMO_COORDINATOR_PASSWORD,
    )
    from supabase import create_client

    service_client = create_client(target.url, target.service_role_key)

    user_id = _find_or_create_demo_user(
        service_client,
        email=DEMO_COORDINATOR_EMAIL,
        password=DEMO_COORDINATOR_PASSWORD,
    )
    access_token = _sign_in_demo_user(
        target, email=DEMO_COORDINATOR_EMAIL, password=DEMO_COORDINATOR_PASSWORD
    )

    from app.auth import AuthedUser

    user = AuthedUser(id=user_id, email=DEMO_COORDINATOR_EMAIL, access_token=access_token)

    # Make the Coordinator's profile row exist (the app's own first-access behaviour).
    from app.services import profile as profile_service

    profile_service.get_or_create_profile(user, first_name=DEMO_COORDINATOR_FIRST_NAME)

    now = datetime.now(timezone.utc)
    print(
        f"Reseeding demo data for {DEMO_COORDINATOR_EMAIL} (user {user_id}) "
        f"as of {now.isoformat()}"
    )

    _clear_existing_demo_data(user)
    summary = _seed_history(user, now)

    print("Demo seed complete:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print(
        f"\nSign in to the demo app as {DEMO_COORDINATOR_EMAIL} "
        f"(password: {DEMO_COORDINATOR_PASSWORD}) to view the populated account."
    )
    return 0


# ---------------------------------------------------------------------------
# Auth: create / sign in the demo Coordinator
# ---------------------------------------------------------------------------


def _find_or_create_demo_user(service_client, *, email: str, password: str) -> str:
    """Return the demo Auth user's id, creating the user if it does not exist (idempotent).

    Uses the service-role admin API (the same privileged identity path the app uses for
    sign-up admin work). The user is created email-confirmed so it can sign in immediately
    with the fixed demo password. On a re-run the existing user is reused (its id is read
    from the admin user list), so the script never creates a second demo Coordinator.
    """
    existing_id = _existing_user_id(service_client, email=email)
    if existing_id is not None:
        print(f"Demo Coordinator already exists (user {existing_id}); reusing it.")
        return existing_id

    response = service_client.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"demo": True, "seeded_by": "scripts/seed_demo_data.py"},
        }
    )
    created = getattr(response, "user", None)
    if created is None or not getattr(created, "id", None):
        raise RuntimeError("Could not create the demo Coordinator (no user returned).")
    print(f"Created demo Coordinator (user {created.id}).")
    return created.id


def _existing_user_id(service_client, *, email: str) -> Optional[str]:
    """The id of the Auth user with this email, or None. Pages the admin list defensively.

    The admin list_users API is paginated; the demo project is tiny, but we still page so
    a busy demo project (or a leftover from an earlier run) is found reliably.
    """
    page = 1
    while True:
        users = service_client.auth.admin.list_users(page=page, per_page=200)
        if not users:
            return None
        for candidate in users:
            if (getattr(candidate, "email", "") or "").lower() == email.lower():
                return candidate.id
        if len(users) < 200:
            return None
        page += 1


def _sign_in_demo_user(target: DemoTarget, *, email: str, password: str) -> str:
    """Sign the demo Coordinator in on the ANON client and return the access token.

    The token is what makes every subsequent write run under the user's own Row Level
    Security (get_anon_client(token)), so the demo data is created exactly as a real
    signed-in request would create it (no service-role shortcut for user data). A fresh
    anon client is used so this carries no other session.
    """
    from supabase import create_client

    anon_client = create_client(target.url, target.anon_key)
    auth_response = anon_client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    session = getattr(auth_response, "session", None)
    if session is None or not getattr(session, "access_token", None):
        raise RuntimeError(
            "Could not sign the demo Coordinator in (no session). Confirm Auth is enabled "
            "on the demo project and email confirmation is not blocking the demo user."
        )
    return session.access_token


# ---------------------------------------------------------------------------
# seeding: drive the REAL services, then backdate the rows onto the timeline
# ---------------------------------------------------------------------------


def _seed_history(user, now: datetime) -> Dict[str, int]:
    """Create both recipients and their full histories through the real services.

    For each recipient: create the child_profile, then for every activity in its blueprint
    (oldest first) prepare the plan (runs the LCE), backdate the activity, record the Pulse
    if any (recomputes the LCI, snapshots it, evaluates the Erosion Alert) at the Pulse's
    past instant, backdate the Pulse + snapshot, and generate any Continuity Card. The
    counts returned are for the run summary.
    """
    from app.services import cards as cards_service
    from app.services import plans as plans_service
    from app.services import profile as profile_service
    from app.services import pulse as pulse_service
    from scripts import demo_data

    counts = {
        "recipients": 0,
        "activities": 0,
        "pulses": 0,
        "cards": 0,
        "alerts_triggered": 0,
    }

    for recipient in demo_data.demo_recipients():
        child = profile_service.create_child(
            user,
            {
                "name": recipient.name,
                "age_band": recipient.age_band,
                "support_level_code": recipient.support_level_code,
                "tags": list(recipient.tags),
            },
        )
        child_id = child["id"]
        counts["recipients"] += 1
        print(f"  Recipient: {recipient.name} ({recipient.support_level_code}) -> child {child_id}")

        # Prepare every activity oldest-first so created_at backdating and the Pulse fold
        # follow the timeline. activity_id is kept so the Pulse and Card target it.
        prepared: Dict[int, str] = {}  # days_ago -> activity_id
        for step in sorted(recipient.activities, key=lambda a: a.days_ago, reverse=True):
            activity_at = demo_data.activity_instant(now, step)
            plan = plans_service.prepare_plan(
                user,
                chapter=step.chapter,
                activity_code=step.activity_code,
                today_flags=list(step.today_flags),
                activity_date=demo_data.activity_date(now, step),
                now=activity_at,
                child_id=child_id,
            )
            prepared[step.days_ago] = plan.activity_id
            counts["activities"] += 1
            _backdate(user, "activity_record", plan.activity_id, {"created_at": activity_at})

        # Record the pulses oldest-first (the order the LCI folds and snapshots), at each
        # Pulse's past instant, then backdate the pulse + its snapshot onto the timeline.
        for step in demo_data.pulse_steps(recipient):
            activity_id = prepared[step.days_ago]
            pulse_at = demo_data.pulse_instant(now, step)
            record = pulse_service.record_pulse(
                user,
                activity_id=activity_id,
                outcome_code=step.pulse.outcome_code,
                challenge_dimension=step.pulse.challenge_dimension,
                now=pulse_at,
            )
            counts["pulses"] += 1
            _backdate(user, "pulse_record", record.id, {"created_at": pulse_at})
            _backdate_snapshots(user, child_id, step.chapter, pulse_at)

        # Generate the Continuity Cards for the marked activities (the helper-facing card).
        for step in demo_data.card_steps(recipient):
            activity_id = prepared[step.days_ago]
            cards_service.create_card(user, activity_id=activity_id, now=now)
            counts["cards"] += 1

    counts["alerts_triggered"] = _count_active_alerts(user)
    return counts


def _backdate(user, table: str, row_id: str, fields: Dict[str, datetime]) -> None:
    """Set timestamp columns on one of the caller's rows (RLS-scoped) to the past instant.

    The services write rows with created_at = DB now(); to build a real six-week history
    we update created_at (and only that) to the blueprint's instant. The update is scoped
    by id AND user_id under the caller's own token, so it can only ever touch the demo
    Coordinator's own rows (RLS is the backstop). Values are written as ISO strings.
    """
    from app.db import get_anon_client

    client = get_anon_client(user.access_token)
    payload = {key: value.isoformat() for key, value in fields.items()}
    client.table(table).update(payload).eq("id", row_id).eq("user_id", user.id).execute()


def _backdate_snapshots(user, child_id: str, chapter: str, taken_at: datetime) -> None:
    """Backdate the lci_snapshot the pulse just wrote for this chapter to the Pulse instant.

    The pulse service writes a snapshot with taken_at = the Pulse's `now` (already the
    past instant we pass), but it stores it with the DB's created_at; we additionally pin
    taken_at to the Pulse instant so the weekly trajectory look-back reads the real date.
    The most recent snapshot for this recipient + chapter is the one the pulse just wrote;
    we update only rows at or after taken_at's date to avoid disturbing earlier weeks.
    """
    from app.db import get_anon_client

    client = get_anon_client(user.access_token)
    # The pulse service already set taken_at to the past instant; this UPDATE makes the
    # stored taken_at exactly the Pulse instant for the row just written (newest for this
    # recipient + chapter), keeping the weekly series consistent with the timeline.
    rows = (
        client.table("lci_snapshot")
        .select("id, taken_at")
        .eq("user_id", user.id)
        .eq("child_id", child_id)
        .eq("chapter", chapter)
        .order("taken_at", desc=True)
        .limit(1)
        .execute()
    )
    data = getattr(rows, "data", None) or []
    if not data:
        return
    newest_id = data[0].get("id")
    if newest_id is None:
        return
    client.table("lci_snapshot").update({"taken_at": taken_at.isoformat()}).eq(
        "id", newest_id
    ).eq("user_id", user.id).execute()


def _count_active_alerts(user) -> int:
    """How many Erosion Alerts are currently active for the demo Coordinator (for the summary).

    Reads the caller's own alert_record rows under RLS. The demo is designed so at least
    one fires NATURALLY from the eroding chapter (verified in tests/test_demo_seed.py);
    this count surfaces it in the run summary so the owner sees the alert landed.
    """
    from app.db import get_anon_client

    client = get_anon_client(user.access_token)
    response = (
        client.table("alert_record")
        .select("id, chapter, level, dismissed, trigger_condition")
        .eq("user_id", user.id)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    active = [r for r in rows if not r.get("dismissed")]
    for r in active:
        print(
            f"    Erosion Alert active: chapter={r.get('chapter')} level=L{r.get('level')} "
            f"({r.get('trigger_condition')})"
        )
    return len(active)


def _clear_existing_demo_data(user) -> None:
    """Delete the demo Coordinator's prior rows so a re-run reseeds cleanly (idempotent).

    Deletes in FK-safe order (children before parents): cards, snapshots, pulses,
    activities, then care recipients. Every delete is scoped to the caller's own user_id
    under RLS, so this can only ever remove the demo Coordinator's own data, never another
    user's. The Auth user and its profile row are kept (find-or-create reuses them).
    """
    from app.db import get_anon_client

    client = get_anon_client(user.access_token)
    for table in (
        "card_record",
        "lci_snapshot",
        "pulse_record",
        "alert_record",
        "activity_record",
        "child_profile",
    ):
        client.table(table).delete().eq("user_id", user.id).execute()
    print("  Cleared any previous demo rows for this Coordinator.")


# ---------------------------------------------------------------------------
# env + cli plumbing
# ---------------------------------------------------------------------------


def _apply_demo_env(target: DemoTarget) -> None:
    """Point the app's settings at the DEMO project before app modules are imported.

    app.db builds its Supabase clients from app.config.settings (SUPABASE_*). We set those
    env vars to the DEMO target so every service call in this run goes to the demo project,
    never the app's own. This is set AFTER the safety guard has already accepted the target.
    """
    os.environ["SUPABASE_URL"] = target.url
    os.environ["SUPABASE_KEY"] = target.anon_key
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = target.service_role_key
    # A DATABASE_URL is not used by the v3 services (they use the Supabase client), but
    # app.config wants the var present; a harmless placeholder keeps settings valid.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://demo:demo@localhost:5432/demo")


def _coordinator_email() -> str:
    from scripts.demo_data import DEMO_COORDINATOR_EMAIL

    return DEMO_COORDINATOR_EMAIL


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_demo_data.py",
        description=(
            "Seed a realistic demo account (one Coordinator, two care recipients, a "
            "six-week six-chapter history with a natural Erosion Alert and Continuity "
            "Cards) into a DEMO / throwaway Supabase project. Drives the real services + "
            "engines so the data is engine-consistent. REFUSES the known production host."
        ),
        epilog=(
            "The target is taken EXPLICITLY (never from the app's SUPABASE_* / .env): set "
            "DEMO_SUPABASE_URL, DEMO_SUPABASE_KEY, DEMO_SUPABASE_SERVICE_ROLE_KEY, or pass "
            "--url / --anon-key / --service-role-key. See scripts/README.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Demo project URL (overrides DEMO_SUPABASE_URL). Must NOT be production.",
    )
    parser.add_argument(
        "--anon-key",
        default=None,
        help="Demo anon key (overrides DEMO_SUPABASE_KEY). Drives the RLS-scoped writes.",
    )
    parser.add_argument(
        "--service-role-key",
        default=None,
        help=(
            "Demo service-role key (overrides DEMO_SUPABASE_SERVICE_ROLE_KEY). Used only to "
            "create / reuse the demo Coordinator in Auth."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Check the target is accepted (not production) and the blueprint composes, then "
            "exit WITHOUT writing any rows."
        ),
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
