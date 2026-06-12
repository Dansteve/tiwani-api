"""The isolation rule (the board's law), proven: no read mixes two care recipients.

Docs/FeatureDecisions.md (Multi Care Recipient): every plan / card / pulse / LCI / alert
belongs to EXACTLY ONE named recipient. There is no household-aggregate score; a read for
recipient A never combines, averages, or cross-references recipient B's data.

The other service tests use the simple FakeClient, which records `.eq` filters but does
NOT filter the data. That proves the right child_id is ON every query. This file proves the
STRONGER property end to end: with a fake that actually applies the child_id filter over a
two-recipient dataset, the LCI fold, the dashboard, and the alert read each return only the
queried recipient's rows, the two recipients produce DIFFERENT independent results, and
swapping the child_id swaps the result. If any read pooled the two, the asserted scores
would collapse to a single mixed value and the test would fail.

No live Supabase (blocked in the sandbox; the task requires mocking). The child_id-aware
fake here is the proof for this session (the migrations are not applied).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pytest

import app.services.alerts as alerts_service
import app.services.chapters as chapters_service
import app.services.lci as lci_service
import app.services.profile as profile_service
from app.auth import AuthedUser

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
USER = AuthedUser(id="u-1", email="ada@example.com", access_token="tok-abc")

# Two care recipients for the one Coordinator (the post-MVP shape the guard gates today).
CHILD_A = "ch-a"  # Sam
CHILD_B = "ch-b"  # Ade


class _Resp:
    """Minimal APIResponse stand-in: the service reads only .data."""

    def __init__(self, data: Any):
        self.data = data


class _ChildScopedQuery:
    """A fluent query that ACTUALLY applies the recorded eq filters to a table's rows.

    Unlike tests.fakes_supabase.FakeQuery (which returns a scripted response regardless of
    the filters), this filters the backing table by the recorded equality predicates on
    execute(), so a query that forgets `.eq("child_id", X)` would (correctly) return BOTH
    recipients' rows and break the per-recipient assertions. That is the point: it makes a
    missing child_id scope observable as mixed data.
    """

    def __init__(self, table: str, rows: List[Dict[str, Any]], log: List[Dict[str, Any]]):
        self._table = table
        self._rows = rows
        self._log = log
        self._filters: List[Tuple[str, Any]] = []

    def select(self, *args: Any, **kwargs: Any) -> "_ChildScopedQuery":
        return self

    def eq(self, column: str, value: Any) -> "_ChildScopedQuery":
        self._filters.append((column, value))
        return self

    def order(self, *args: Any, **kwargs: Any) -> "_ChildScopedQuery":
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "_ChildScopedQuery":
        return self

    def execute(self) -> _Resp:
        self._log.append({"table": self._table, "filters": list(self._filters)})
        matched = [
            row
            for row in self._rows
            if all(row.get(col) == val for col, val in self._filters)
        ]
        return _Resp(matched)


class _ChildScopedClient:
    """A read-only fake whose table(name) filters that table's seeded rows by the eq predicates."""

    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self._tables = tables
        self.calls: List[Dict[str, Any]] = []

    def table(self, name: str) -> _ChildScopedQuery:
        return _ChildScopedQuery(name, self._tables.get(name, []), self.calls)


def _pulse(child_id: str, chapter: str, outcome: str, tier: str, day: int) -> Dict[str, Any]:
    return {
        "user_id": "u-1",
        "child_id": child_id,
        "chapter": chapter,
        "outcome_code": outcome,
        "tier_recommended": tier,
        "created_at": f"2026-06-{day:02d}T09:00:00+00:00",
    }


# A two-recipient world, same chapter (travel), deliberately divergent so a mix is visible:
#   - Sam (CHILD_A): two Well/Modified pulses -> 50 +7 +5 = 62.
#   - Ade (CHILD_B): one Difficult/Full pulse -> 50 -8 = 42.
# If any fold pooled the two, travel would be neither 62 nor 42 (it would fold all three),
# so the distinct 62 / 42 assertions are the isolation proof.
TABLES = {
    "child_profile": [
        {"id": CHILD_A, "user_id": "u-1", "name": "Sam"},
        {"id": CHILD_B, "user_id": "u-1", "name": "Ade"},
    ],
    "pulse_record": [
        _pulse(CHILD_A, "travel", "well", "Modified", 10),
        _pulse(CHILD_A, "travel", "okay", "Modified", 12),
        _pulse(CHILD_B, "travel", "difficult", "Full", 11),
    ],
    "lci_snapshot": [],
    "activity_record": [
        {"user_id": "u-1", "child_id": CHILD_A, "chapter": "travel",
         "tier": "Modified", "created_at": "2026-06-10T09:00:00+00:00"},
        {"user_id": "u-1", "child_id": CHILD_B, "chapter": "travel",
         "tier": "Full", "created_at": "2026-06-11T09:00:00+00:00"},
    ],
    "alert_record": [
        {"user_id": "u-1", "child_id": CHILD_A, "chapter": "travel",
         "level": 1, "trigger_condition": "l1_counts_30d",
         "dismissed": False, "dismissed_level": None},
        {"user_id": "u-1", "child_id": CHILD_B, "chapter": "career",
         "level": 3, "trigger_condition": "l3_lci_below_30",
         "dismissed": False, "dismissed_level": None},
    ],
}


@pytest.fixture
def scoped(monkeypatch):
    """Point the LCI, chapters, alerts, and profile (resolver) clients at one scoped fake."""
    client = _ChildScopedClient(TABLES)
    for module in (lci_service, chapters_service, alerts_service, profile_service):
        monkeypatch.setattr(module, "get_anon_client", lambda token=None, _c=client: _c)
    return client


# ---------------------------------------------------------------------------
# LCI: each recipient's chapter score is its own, never the two pooled
# ---------------------------------------------------------------------------


def test_lci_chapter_score_is_per_recipient(scoped):
    a = {c.chapter: c for c in lci_service.chapter_lci_list(USER, child_id=CHILD_A, now=NOW)}
    b = {c.chapter: c for c in lci_service.chapter_lci_list(USER, child_id=CHILD_B, now=NOW)}

    # Sam's travel folds only Sam's two pulses (62); Ade's only Ade's one (42).
    assert a["travel"].score == 62
    assert a["travel"].pulse_count == 2
    assert b["travel"].score == 42
    assert b["travel"].pulse_count == 1
    # The mixed fold of all three would be neither value: the scores prove no mixing.
    assert a["travel"].score != b["travel"].score


def test_overall_lci_is_one_recipients_resilience_not_a_household_aggregate(scoped):
    a = lci_service.overall_lci(USER, child_id=CHILD_A, now=NOW)
    b = lci_service.overall_lci(USER, child_id=CHILD_B, now=NOW)
    # Each overall is that recipient's single travel chapter, not an average across both.
    assert a.score == 62
    assert b.score == 42
    assert list(a.chapters_included) == ["travel"]
    assert list(b.chapters_included) == ["travel"]


# ---------------------------------------------------------------------------
# Dashboard: the per-chapter card belongs to exactly one recipient
# ---------------------------------------------------------------------------


def test_dashboard_chapter_card_is_per_recipient(scoped):
    a = {s.chapter: s for s in chapters_service.list_chapter_statuses(USER, CHILD_A)}
    b = {s.chapter: s for s in chapters_service.list_chapter_statuses(USER, CHILD_B)}

    # Sam: one travel activity, travel LCI 62, travel alert L1, no career alert.
    assert a["travel"].activity_count == 1
    assert a["travel"].lci == 62
    assert a["travel"].alert_level == 1
    assert a["career"].alert_level is None
    # Ade: one travel activity, travel LCI 42, NO travel alert, career alert L3.
    assert b["travel"].activity_count == 1
    assert b["travel"].lci == 42
    assert b["travel"].alert_level is None
    assert b["career"].alert_level == 3


# ---------------------------------------------------------------------------
# Alerts: one recipient's alert list never carries another recipient's alert
# ---------------------------------------------------------------------------


def test_alert_list_is_scoped_to_one_recipient(scoped):
    a = {al.chapter: al for al in alerts_service.list_active_alerts(USER, CHILD_A)}
    b = {al.chapter: al for al in alerts_service.list_active_alerts(USER, CHILD_B)}

    # Sam has only the travel L1; Ade has only the career L3. Neither leaks into the other.
    assert set(a.keys()) == {"travel"}
    assert a["travel"].level == 1
    assert set(b.keys()) == {"career"}
    assert b["career"].level == 3


def test_swapping_child_id_swaps_the_result(scoped):
    # The same call with a different child_id returns the OTHER recipient's data, proving
    # the child_id is the scope key and nothing is shared or cached across recipients.
    travel_a = next(
        c for c in lci_service.chapter_lci_list(USER, child_id=CHILD_A, now=NOW)
        if c.chapter == "travel"
    )
    travel_b = next(
        c for c in lci_service.chapter_lci_list(USER, child_id=CHILD_B, now=NOW)
        if c.chapter == "travel"
    )
    assert (travel_a.score, travel_b.score) == (62, 42)


# ---------------------------------------------------------------------------
# Every scoped read actually carried the child_id (no un-scoped read slipped through)
# ---------------------------------------------------------------------------


def test_no_per_recipient_read_omits_the_child_id_filter(scoped):
    # Drive all the per-recipient reads for ONE recipient, then assert every query against
    # a per-recipient table carried child_id == CHILD_A (never the other, never unscoped).
    lci_service.chapter_lci_list(USER, child_id=CHILD_A, now=NOW)
    lci_service.overall_lci(USER, child_id=CHILD_A, now=NOW)
    chapters_service.list_chapter_statuses(USER, CHILD_A)
    alerts_service.list_active_alerts(USER, CHILD_A)

    per_recipient_tables = {"pulse_record", "lci_snapshot", "activity_record", "alert_record"}
    for call in scoped.calls:
        if call["table"] in per_recipient_tables:
            child_filters = {v for (col, v) in call["filters"] if col == "child_id"}
            assert child_filters == {CHILD_A}, (
                f"a {call['table']} read was not scoped to the single recipient: {call}"
            )
