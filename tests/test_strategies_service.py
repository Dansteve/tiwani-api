"""Behaviour tests for the Strategy Library service (Product.md section 4.10).

These prove the section 4.10 rules end to end against a stateful, child-scoped fake Supabase
(no live DB; the sandbox blocks it and the task requires mocking). The fake actually filters by
the recorded eq predicates AND applies inserts/updates to a backing store, so:
  - a query that forgets `.eq("child_id", X)` would return the wrong recipient's rows and break
    the per-recipient assertions (the isolation proof), and
  - an update is observable in a later read (so promotion/suppression/attribution state is real,
    not scripted).

Covered (the task's required cases): the promotion threshold drives ranking-first, the
suppression threshold (3x, scenario-specific, reversible via re-allow), cross-context surfacing
+ per-chapter dismiss, equal outcome attribution across every strategy in a plan, and two-
recipient isolation (a library item for child A never affects child B's ranking or counts).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

import pytest

import app.services.plans as plans_service
import app.services.strategies as strategy_library
from app.auth import AuthedUser

USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")
CHILD_A = "ch-a"
CHILD_B = "ch-b"


# ---------------------------------------------------------------------------
# A stateful, child-scoped fake Supabase for the strategy_library_item table.
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, data: Any):
        self.data = data


class _Query:
    """A fluent query that filters and mutates a shared list of rows on execute().

    Supports select (returns the rows matching the recorded eq filters), insert (appends a row
    with a generated id), and update (sets fields on the rows matching the eq filters). It
    records its eq filters so a test can assert child_id scoping, and it actually applies the
    filter, so a missing child_id scope returns the wrong rows (the isolation proof).
    """

    def __init__(self, table: str, store: List[Dict[str, Any]], log: List[Dict[str, Any]]):
        self._table = table
        self._store = store
        self._log = log
        self._op = "select"
        self._payload: Any = None
        self._update_fields: Optional[Dict[str, Any]] = None
        self._filters: List[Tuple[str, Any]] = []

    def select(self, *a: Any, **k: Any) -> "_Query":
        self._op = "select"
        return self

    def insert(self, payload: Any, *a: Any, **k: Any) -> "_Query":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, fields: Dict[str, Any], *a: Any, **k: Any) -> "_Query":
        self._op = "update"
        self._update_fields = fields
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append((column, value))
        return self

    def order(self, *a: Any, **k: Any) -> "_Query":
        return self

    def limit(self, *a: Any, **k: Any) -> "_Query":
        return self

    def _matches(self, row: Dict[str, Any]) -> bool:
        return all(row.get(col) == val for col, val in self._filters)

    def execute(self) -> _Resp:
        self._log.append({"table": self._table, "op": self._op, "filters": list(self._filters)})
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", str(uuid.uuid4()))
            # Apply the column defaults the migration would, so a freshly inserted row reads
            # back with the same shape a real insert returns.
            row.setdefault("positive_count", 0)
            row.setdefault("negative_count", 0)
            row.setdefault("removal_count", 0)
            row.setdefault("promoted", False)
            row.setdefault("suppressed", False)
            row.setdefault("cross_context_dismissed_chapters", [])
            row.setdefault("description", row.get("description", ""))
            self._store.append(row)
            return _Resp([row])
        if self._op == "update":
            updated = [r for r in self._store if self._matches(r)]
            for r in updated:
                r.update(self._update_fields or {})
            return _Resp(list(updated))
        # select
        return _Resp([dict(r) for r in self._store if self._matches(r)])


class _Client:
    def __init__(self, store: List[Dict[str, Any]]):
        self._store = store
        self.calls: List[Dict[str, Any]] = []

    def table(self, name: str) -> _Query:
        return _Query(name, self._store, self.calls)


@pytest.fixture
def store() -> List[Dict[str, Any]]:
    return []


@pytest.fixture
def patched(monkeypatch, store):
    """Point the strategy library service's client at the stateful fake."""
    client = _Client(store)
    monkeypatch.setattr(strategy_library, "get_anon_client", lambda token=None, _c=client: _c)
    return client


def _seed_item(store, **overrides) -> Dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "user_id": "u-1",
        "child_id": CHILD_A,
        "chapter": "travel",
        "scenario_type": "airport",
        "title": "Lanyard",
        "description": "Request the lanyard",
        "dimension_tags": ["sensory"],
        "positive_count": 0,
        "negative_count": 0,
        "removal_count": 0,
        "promoted": False,
        "suppressed": False,
        "cross_context_dismissed_chapters": [],
    }
    row.update(overrides)
    store.append(row)
    return row


# ---------------------------------------------------------------------------
# Auto-save: each plan strategy is saved once per recipient + scenario (idempotent)
# ---------------------------------------------------------------------------


def test_auto_save_inserts_each_strategy_once(patched, store):
    strategies = [
        {"title": "Lanyard", "detail": "Request the lanyard"},
        {"title": "Quiet room", "detail": "Ask about a quiet room"},
    ]
    strategy_library.auto_save_plan_strategies(
        USER,
        child_id=CHILD_A,
        chapter="travel",
        scenario_type="airport",
        strategies=strategies,
        high_dimensions=["sensory"],
    )
    assert {r["title"] for r in store} == {"Lanyard", "Quiet room"}
    # The saved dimension tags are the scenario's high dimensions (the cross-context signal).
    assert all(r["dimension_tags"] == ["sensory"] for r in store)

    # A re-plan does not duplicate (idempotent on the title within the scenario).
    strategy_library.auto_save_plan_strategies(
        USER,
        child_id=CHILD_A,
        chapter="travel",
        scenario_type="airport",
        strategies=strategies,
        high_dimensions=["sensory"],
    )
    assert len(store) == 2


def test_auto_save_does_not_resave_a_cross_context_strategy(patched, store):
    # A strategy appended from another chapter (also_worked_in_chapter set) is NOT a strategy
    # of this scenario; it is saved under its own scenario, so auto-save skips it here.
    strategy_library.auto_save_plan_strategies(
        USER,
        child_id=CHILD_A,
        chapter="travel",
        scenario_type="airport",
        strategies=[{"title": "From social", "detail": "x", "also_worked_in_chapter": "social"}],
        high_dimensions=["sensory"],
    )
    assert store == []


# ---------------------------------------------------------------------------
# Promotion drives ranking-first; suppression excludes
# ---------------------------------------------------------------------------


def test_ranking_inputs_promote_a_promoted_strategy(patched, store):
    _seed_item(store, title="Lanyard", positive_count=2, negative_count=0)
    _seed_item(store, title="Quiet room", positive_count=0, negative_count=0)
    inputs = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport", high_dimensions=[]
    )
    assert inputs.promoted_titles == ["Lanyard"]
    assert "Quiet room" not in inputs.promoted_titles
    # Every saved title is mapped to its id so the plan can carry library_item_id.
    assert set(inputs.item_id_by_title.keys()) == {"Lanyard", "Quiet room"}


def test_ranking_inputs_exclude_a_suppressed_strategy(patched, store):
    _seed_item(store, title="Lanyard", suppressed=True, removal_count=3)
    _seed_item(store, title="Quiet room")
    inputs = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport", high_dimensions=[]
    )
    assert inputs.suppressed_titles == ["Lanyard"]
    # A suppressed strategy is never also promoted.
    assert "Lanyard" not in inputs.promoted_titles


def test_apply_library_orders_promoted_first_and_drops_suppressed():
    # The plan-side overlay (the actual ranking change the engine result gets): promoted floats
    # to the front, suppressed is dropped, the rest keep their engine order. Pure, no DB.
    class _S:
        def __init__(self, title):
            self.title = title
            self.body = title + " body"
            self.cross_context_chapter = None

    engine_strategies = [_S("A"), _S("B"), _S("C")]
    inputs = strategy_library.StrategyLibraryInputs(
        promoted_titles=["C"],
        suppressed_titles=["A"],
        item_id_by_title={"B": "id-b", "C": "id-c"},
        cross_context=[],
    )
    ordered = plans_service._apply_library(engine_strategies, inputs)
    assert [s.title for s in ordered] == ["C", "B"]  # C promoted first, A suppressed out
    assert ordered[0].library_item_id == "id-c"
    assert ordered[1].library_item_id == "id-b"


# ---------------------------------------------------------------------------
# Suppression: 3 removals, scenario-specific, reversible
# ---------------------------------------------------------------------------


def test_suppression_after_three_removals_and_reallow(patched, store):
    item = _seed_item(store, title="Lanyard")
    item_id = item["id"]

    v1 = strategy_library.remove_strategy(USER, item_id)
    assert v1.removal_count == 1 and v1.suppressed is False
    v2 = strategy_library.remove_strategy(USER, item_id)
    assert v2.removal_count == 2 and v2.suppressed is False
    v3 = strategy_library.remove_strategy(USER, item_id)
    # The third removal suppresses it (the exact threshold).
    assert v3.removal_count == 3 and v3.suppressed is True

    # Re-allow is reversible: it clears the marker and resets the count.
    allowed = strategy_library.allow_strategy(USER, item_id)
    assert allowed.suppressed is False and allowed.removal_count == 0


def test_suppression_is_scenario_specific(patched, store):
    # The same strategy title in two scenarios: removing it 3 times in "airport" suppresses it
    # THERE, while the "security-queue" scenario's copy is untouched.
    airport = _seed_item(store, title="Lanyard", scenario_type="airport")
    _seed_item(store, title="Lanyard", scenario_type="security-queue")

    for _ in range(3):
        strategy_library.remove_strategy(USER, airport["id"])

    airport_items = strategy_library._scenario_items(USER, CHILD_A, "travel", "airport")
    queue_items = strategy_library._scenario_items(USER, CHILD_A, "travel", "security-queue")
    assert airport_items[0]["suppressed"] is True
    assert queue_items[0]["suppressed"] is False  # the other scenario is unaffected


# ---------------------------------------------------------------------------
# Equal outcome attribution across every strategy in a plan
# ---------------------------------------------------------------------------


def test_equal_attribution_applies_outcome_to_every_strategy(patched, store):
    _seed_item(store, title="Lanyard")
    _seed_item(store, title="Quiet room")
    plan_strategies = [{"title": "Lanyard"}, {"title": "Quiet room"}]

    # A "well" outcome is positive for EVERY strategy in the plan (equal attribution).
    strategy_library.apply_pulse_outcome(
        USER,
        child_id=CHILD_A,
        chapter="travel",
        scenario_type="airport",
        plan_strategies=plan_strategies,
        outcome_code="well",
    )
    rows = {r["title"]: r for r in store}
    assert rows["Lanyard"]["positive_count"] == 1
    assert rows["Quiet room"]["positive_count"] == 1

    # A second "well" promotes both (positives reach 2, > negatives 0): the cached flag flips.
    strategy_library.apply_pulse_outcome(
        USER,
        child_id=CHILD_A,
        chapter="travel",
        scenario_type="airport",
        plan_strategies=plan_strategies,
        outcome_code="well",
    )
    rows = {r["title"]: r for r in store}
    assert rows["Lanyard"]["positive_count"] == 2 and rows["Lanyard"]["promoted"] is True
    assert rows["Quiet room"]["positive_count"] == 2 and rows["Quiet room"]["promoted"] is True


def test_difficult_is_a_negative_and_skipped_moves_nothing(patched, store):
    _seed_item(store, title="Lanyard")
    plan = [{"title": "Lanyard"}]

    strategy_library.apply_pulse_outcome(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        plan_strategies=plan, outcome_code="difficult",
    )
    assert store[0]["negative_count"] == 1 and store[0]["positive_count"] == 0

    # A skipped pulse moves neither count (section 4.10: skipped has no effect).
    strategy_library.apply_pulse_outcome(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        plan_strategies=plan, outcome_code="skipped",
    )
    assert store[0]["negative_count"] == 1 and store[0]["positive_count"] == 0


# ---------------------------------------------------------------------------
# Cross-context surfacing + per-chapter dismiss
# ---------------------------------------------------------------------------


def test_cross_context_surfaces_successful_other_chapter_strategy(patched, store):
    # A strategy successful in "social" (2 positives), tagged sensory, surfaces in a "travel"
    # plan whose sensory is high (>= 3).
    _seed_item(
        store,
        title="Ear defenders",
        chapter="social",
        scenario_type="party",
        dimension_tags=["sensory"],
        positive_count=2,
    )
    inputs = strategy_library.ranking_inputs_for_plan(
        USER,
        child_id=CHILD_A,
        chapter="travel",
        scenario_type="airport",
        high_dimensions=["sensory"],
    )
    assert len(inputs.cross_context) == 1
    cc = inputs.cross_context[0]
    assert cc.title == "Ear defenders"
    assert cc.source_chapter == "social"
    # The label resolves the source chapter to its display name.
    assert strategy_library.cross_context_label("social") == "Also worked in Social & Community"


def test_cross_context_requires_a_high_dimension_match(patched, store):
    # The same successful strategy does NOT surface when its dimension is not high here.
    _seed_item(
        store, title="Ear defenders", chapter="social", scenario_type="party",
        dimension_tags=["sensory"], positive_count=2,
    )
    inputs = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        high_dimensions=["temporal"],  # sensory is not high here
    )
    assert inputs.cross_context == []


def test_cross_context_below_the_positive_gate_does_not_surface(patched, store):
    _seed_item(
        store, title="Ear defenders", chapter="social", scenario_type="party",
        dimension_tags=["sensory"], positive_count=1,  # below >= 2
    )
    inputs = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        high_dimensions=["sensory"],
    )
    assert inputs.cross_context == []


def test_cross_context_dismiss_is_per_chapter(patched, store):
    item = _seed_item(
        store, title="Ear defenders", chapter="social", scenario_type="party",
        dimension_tags=["sensory"], positive_count=2,
    )
    # Dismiss the surfacing for travel.
    view = strategy_library.dismiss_cross_context(USER, item["id"], "travel")
    assert view.library_item_id == item["id"]

    # It no longer surfaces in travel...
    travel_inputs = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        high_dimensions=["sensory"],
    )
    assert travel_inputs.cross_context == []

    # ...but still surfaces in another chapter (culture) where it was not dismissed.
    culture_inputs = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="culture", scenario_type="service",
        high_dimensions=["sensory"],
    )
    assert [c.title for c in culture_inputs.cross_context] == ["Ear defenders"]


# ---------------------------------------------------------------------------
# Two-recipient isolation: child A's library never affects child B
# ---------------------------------------------------------------------------


def test_promotion_is_per_recipient(patched, store):
    # The SAME title + scenario for two recipients, promoted only for A.
    _seed_item(store, child_id=CHILD_A, title="Lanyard", positive_count=2)
    _seed_item(store, child_id=CHILD_B, title="Lanyard", positive_count=0)

    a = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport", high_dimensions=[]
    )
    b = strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_B, chapter="travel", scenario_type="airport", high_dimensions=[]
    )
    assert a.promoted_titles == ["Lanyard"]
    assert b.promoted_titles == []  # B's identical-title strategy is NOT promoted


def test_outcome_attribution_is_per_recipient(patched, store):
    _seed_item(store, child_id=CHILD_A, title="Lanyard")
    _seed_item(store, child_id=CHILD_B, title="Lanyard")

    # A pulse for child A updates only A's counts; B's identical-title item is untouched.
    strategy_library.apply_pulse_outcome(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        plan_strategies=[{"title": "Lanyard"}], outcome_code="well",
    )
    rows = {r["child_id"]: r for r in store}
    assert rows[CHILD_A]["positive_count"] == 1
    assert rows[CHILD_B]["positive_count"] == 0  # the other recipient is untouched


def test_every_library_read_carries_the_child_id_filter(patched, store):
    _seed_item(store, child_id=CHILD_A, title="Lanyard")
    strategy_library.ranking_inputs_for_plan(
        USER, child_id=CHILD_A, chapter="travel", scenario_type="airport",
        high_dimensions=["sensory"],
    )
    # Every strategy_library_item read was scoped to the single recipient (the isolation rule).
    for call in patched.calls:
        if call["table"] == "strategy_library_item" and call["op"] == "select":
            child_filters = {v for (col, v) in call["filters"] if col == "child_id"}
            assert child_filters == {CHILD_A}, f"a library read was not child-scoped: {call}"
