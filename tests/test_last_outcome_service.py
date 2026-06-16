"""Behaviour tests for the "What helped last time" service (ProductReview.md item 5).

These prove the prepare-time recall read against a stateful, child + chapter-scoped fake
Supabase (no live DB; the sandbox blocks it and the task requires mocking). The fake actually
filters by the recorded eq predicates and sorts on order(), so:
  - a query that forgets `.eq("child_id", X)` or `.eq("chapter", C)` would read the wrong
    rows and break the per-recipient / per-chapter assertions (the isolation proof), and
  - the order("created_at", desc=True) is honoured, so "most recent prior outcome" is real.

Covered (the task's required cases): the most recent NON-skipped pulse is recalled (a skipped
pulse is not an outcome), its stored outcome + tier + challenge dimension are carried, a §4.10
PROMOTED strategy surfaces as worked_strategy (and an unpromoted one does not), pivot_helped is
the grounded stored-fact flag, a first-time chapter (and only-skipped history) returns None, and
two-recipient isolation (child A's pulses never surface for child B).

This is a READ of stored facts: the service runs NO scoring (no LCE, no tier re-derivation, no
index), so the assertions are about what it READS BACK, never a number it computed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

import app.services.last_outcome as last_outcome_service
from app.auth import AuthedUser

USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")
CHILD_A = "ch-a"
CHILD_B = "ch-b"


# ---------------------------------------------------------------------------
# A stateful, scoped fake Supabase across the three tables the read touches.
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, data: Any):
        self.data = data


class _Query:
    """A fluent query that filters + sorts a table's rows on execute().

    Records its eq filters and applies them, so a missing child_id / chapter scope returns the
    wrong rows (the isolation proof). Honours order(col, desc) and limit(n) so "most recent
    first" and the bounded cap are real.
    """

    def __init__(
        self,
        table: str,
        store: Dict[str, List[Dict[str, Any]]],
        log: List[Dict[str, Any]],
    ):
        self._table = table
        self._store = store
        self._log = log
        self._filters: List[Tuple[str, Any]] = []
        self._order: Optional[Tuple[str, bool]] = None
        self._limit: Optional[int] = None

    def select(self, *a: Any, **k: Any) -> "_Query":
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append((column, value))
        return self

    def order(self, column: str, desc: bool = False, **k: Any) -> "_Query":
        self._order = (column, desc)
        return self

    def limit(self, n: int) -> "_Query":
        self._limit = n
        return self

    def _matches(self, row: Dict[str, Any]) -> bool:
        return all(row.get(col) == val for col, val in self._filters)

    def execute(self) -> _Resp:
        self._log.append({"table": self._table, "filters": list(self._filters)})
        rows = [dict(r) for r in self._store.get(self._table, []) if self._matches(r)]
        if self._order is not None:
            col, desc = self._order
            rows.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Resp(rows)


class _Client:
    def __init__(self, store: Dict[str, List[Dict[str, Any]]]):
        self._store = store
        self.calls: List[Dict[str, Any]] = []

    def table(self, name: str) -> _Query:
        return _Query(name, self._store, self.calls)


@pytest.fixture
def store() -> Dict[str, List[Dict[str, Any]]]:
    return {"pulse_record": [], "activity_record": [], "strategy_library_item": []}


@pytest.fixture
def patched(monkeypatch, store):
    """Point the service AND its resolve_child_id chokepoint at the stateful fake."""
    client = _Client(store)
    monkeypatch.setattr(
        last_outcome_service, "get_anon_client", lambda token=None, _c=client: _c
    )

    # resolve_child_id is imported into the service module; stub it to the explicit id (or the
    # sole child) without a DB round-trip, mirroring its real contract (a forged id raises).
    def _resolve(_user, child_id=None):
        if child_id is not None:
            if child_id not in (CHILD_A, CHILD_B):
                from app.services.profile import ChildNotFoundError

                raise ChildNotFoundError("No care recipient found for this id")
            return child_id
        return CHILD_A

    monkeypatch.setattr(last_outcome_service, "resolve_child_id", _resolve)
    return client


def _iso(year: int, month: int, day: int) -> str:
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc).isoformat()


def _seed_pulse(
    store,
    *,
    child_id: str = CHILD_A,
    chapter: str = "school",
    outcome: str = "well",
    tier: str = "Full",
    challenge: Optional[str] = "sensory",
    created_at: str,
    activity_id: Optional[str] = None,
) -> str:
    aid = activity_id or str(uuid.uuid4())
    store["pulse_record"].append(
        {
            "id": str(uuid.uuid4()),
            "user_id": "u-1",
            "child_id": child_id,
            "chapter": chapter,
            "activity_id": aid,
            "outcome_code": outcome,
            "tier_recommended": tier,
            "challenge_dimension": challenge,
            "created_at": created_at,
        }
    )
    return aid


def _seed_activity(store, activity_id: str, *, child_id: str = CHILD_A, name: str = "Drop-off"):
    store["activity_record"].append(
        {
            "id": activity_id,
            "user_id": "u-1",
            "child_id": child_id,
            "activity_name": name,
        }
    )


def _seed_strategy(
    store,
    *,
    child_id: str = CHILD_A,
    chapter: str = "school",
    title: str,
    positive: int,
    negative: int = 0,
    suppressed: bool = False,
):
    store["strategy_library_item"].append(
        {
            "id": str(uuid.uuid4()),
            "user_id": "u-1",
            "child_id": child_id,
            "chapter": chapter,
            "title": title,
            "positive_count": positive,
            "negative_count": negative,
            "suppressed": suppressed,
        }
    )


# ---------------------------------------------------------------------------
# the recall: the most recent NON-skipped prior outcome
# ---------------------------------------------------------------------------


def test_returns_the_most_recent_prior_outcome(patched, store):
    aid_old = _seed_pulse(store, outcome="difficult", tier="Full", created_at=_iso(2026, 5, 1))
    aid_new = _seed_pulse(
        store, outcome="okay", tier="Modified", challenge="human", created_at=_iso(2026, 6, 1)
    )
    _seed_activity(store, aid_old, name="Old day")
    _seed_activity(store, aid_new, name="Assembly")

    result = last_outcome_service.get_last_outcome(USER, chapter="school")

    assert result is not None
    # The NEWER pulse is recalled (its stored fields are carried verbatim, never re-derived).
    assert result.outcome_code == "okay"
    assert result.tier_recommended == "Modified"
    assert result.challenge_dimension == "human"
    assert result.activity_name == "Assembly"
    assert result.chapter == "school"


def test_a_skipped_pulse_is_not_recalled(patched, store):
    # The most recent pulse is SKIPPED (dismissed twice); the recall reaches past it to the most
    # recent real outcome, because a skip is not an outcome to recall.
    aid_real = _seed_pulse(store, outcome="well", tier="Full", created_at=_iso(2026, 5, 20))
    _seed_pulse(store, outcome="skipped", tier="Full", challenge=None, created_at=_iso(2026, 6, 5))
    _seed_activity(store, aid_real, name="Library visit")

    result = last_outcome_service.get_last_outcome(USER, chapter="school")

    assert result is not None
    assert result.outcome_code == "well"
    assert result.activity_name == "Library visit"


def test_first_time_chapter_returns_none(patched, store):
    # A pulse exists in ANOTHER chapter, but none in the requested one: a first-time chapter, so
    # the recall is None (the app shows nothing).
    aid = _seed_pulse(store, chapter="travel", outcome="well", created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid)

    assert last_outcome_service.get_last_outcome(USER, chapter="school") is None


def test_only_skipped_history_returns_none(patched, store):
    _seed_pulse(store, outcome="skipped", challenge=None, created_at=_iso(2026, 6, 1))
    _seed_pulse(store, outcome="skipped", challenge=None, created_at=_iso(2026, 6, 2))
    assert last_outcome_service.get_last_outcome(USER, chapter="school") is None


def test_no_recipient_returns_none(patched, monkeypatch, store):
    # resolve_child_id returns None (a fresh user with no recipient): the recall is None.
    monkeypatch.setattr(last_outcome_service, "resolve_child_id", lambda _u, child_id=None: None)
    assert last_outcome_service.get_last_outcome(USER, chapter="school") is None


# ---------------------------------------------------------------------------
# worked_strategy: a §4.10 PROMOTED strategy for the recipient + chapter
# ---------------------------------------------------------------------------


def test_promoted_strategy_surfaces_as_worked(patched, store):
    aid = _seed_pulse(store, outcome="well", created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid)
    # Promoted: positives >= 2 AND positives > negatives (the §4.10 rule).
    _seed_strategy(store, title="Arrive early", positive=3, negative=1)

    result = last_outcome_service.get_last_outcome(USER, chapter="school")

    assert result is not None
    assert result.worked_strategy == "Arrive early"


def test_unpromoted_strategy_does_not_surface(patched, store):
    aid = _seed_pulse(store, outcome="well", created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid)
    # NOT promoted: only 1 positive (below the >= 2 bar), and a 2-2 tie is not net-helped.
    _seed_strategy(store, title="One use", positive=1, negative=0)
    _seed_strategy(store, title="Even", positive=2, negative=2)

    result = last_outcome_service.get_last_outcome(USER, chapter="school")

    assert result is not None
    assert result.worked_strategy is None


def test_most_positive_promoted_strategy_wins(patched, store):
    aid = _seed_pulse(store, outcome="well", created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid)
    _seed_strategy(store, title="Good", positive=2, negative=0)
    _seed_strategy(store, title="Best", positive=5, negative=1)
    # A suppressed strategy never surfaces, even if it would otherwise be the most positive.
    _seed_strategy(store, title="Suppressed", positive=9, negative=0, suppressed=True)

    result = last_outcome_service.get_last_outcome(USER, chapter="school")

    assert result is not None
    assert result.worked_strategy == "Best"


def test_worked_strategy_read_failure_falls_open(patched, store, monkeypatch):
    # The strategy library table is not applied yet (0014 pending): the read raises, and the recall
    # still returns the pulse facts with worked_strategy null (graceful degradation).
    aid = _seed_pulse(store, outcome="well", created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid)

    real_table = patched.table

    def _boom(name):
        if name == "strategy_library_item":
            raise RuntimeError("relation strategy_library_item does not exist")
        return real_table(name)

    monkeypatch.setattr(patched, "table", _boom)

    result = last_outcome_service.get_last_outcome(USER, chapter="school")
    assert result is not None
    assert result.worked_strategy is None


# ---------------------------------------------------------------------------
# pivot_helped: the grounded stored-fact flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome,tier,expected",
    [
        ("well", "Pivot", True),  # positive under Pivot
        ("okay", "Pivot", True),  # positive under Pivot
        ("difficult", "Pivot", True),  # §4.8: Difficult under Pivot is positive (plan protected)
        ("well", "Full", False),  # not Pivot
        ("okay", "Modified", False),  # not Pivot
        ("difficult", "Full", False),  # negative, not Pivot
    ],
)
def test_pivot_helped_is_grounded(patched, store, outcome, tier, expected):
    aid = _seed_pulse(store, outcome=outcome, tier=tier, created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid)

    result = last_outcome_service.get_last_outcome(USER, chapter="school")
    assert result is not None
    assert result.pivot_helped is expected


# ---------------------------------------------------------------------------
# isolation: child A's outcomes never surface for child B
# ---------------------------------------------------------------------------


def test_recall_is_per_recipient(patched, store):
    # Child A has a school outcome; child B has none in school.
    aid_a = _seed_pulse(store, child_id=CHILD_A, outcome="well", created_at=_iso(2026, 6, 1))
    _seed_activity(store, aid_a, child_id=CHILD_A)
    _seed_strategy(store, child_id=CHILD_A, title="A only", positive=3)

    # Reading for child B (who has no school pulse) returns None: A's data never leaks.
    assert last_outcome_service.get_last_outcome(USER, chapter="school", child_id=CHILD_B) is None
    # Reading for child A returns A's outcome.
    result_a = last_outcome_service.get_last_outcome(USER, chapter="school", child_id=CHILD_A)
    assert result_a is not None
    assert result_a.worked_strategy == "A only"


def test_unowned_child_id_raises(patched, store):
    from app.services.profile import ChildNotFoundError

    with pytest.raises(ChildNotFoundError):
        last_outcome_service.get_last_outcome(USER, chapter="school", child_id="not-mine")
