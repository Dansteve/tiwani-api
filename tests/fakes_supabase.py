"""A no-network fake Supabase client for the service/route tests.

The real supabase client builds a fluent query (table -> select/insert/update ->
filters -> execute) and only opens a connection on execute(). These fakes record
the calls and return scripted APIResponse-like objects, so the profile service
and the v3 routes can be unit-tested without a live Supabase (the sandbox blocks
it, and per the task tests must mock the client; HardRules/Api/SETUP.md testing).

A FakeResponse mirrors the .data attribute the service reads (_rows/_first in
app/services/profile). A FakeQuery records the operation and the filters and,
on execute(), returns the response the test scripted for (table, operation).
FakeClient.table(name) hands back a FakeQuery bound to the scripted responses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class FakeResponse:
    """Mirror of the supabase APIResponse: only .data is read by the service."""

    def __init__(self, data: Any):
        self.data = data


class FakeQuery:
    """A recording fluent query builder. All chain methods return self."""

    def __init__(self, table: str, log: List[Dict[str, Any]], scripts: Dict[Tuple[str, str], Any]):
        self._table = table
        self._log = log
        self._scripts = scripts
        self._op: Optional[str] = None
        self._payload: Any = None
        self._filters: List[Tuple[str, Any]] = []
        self._single = False

    # --- operations -------------------------------------------------------
    def select(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        self._op = "select"
        return self

    def insert(self, payload: Any, *args: Any, **kwargs: Any) -> "FakeQuery":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: Any, *args: Any, **kwargs: Any) -> "FakeQuery":
        self._op = "update"
        self._payload = payload
        return self

    def delete(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        self._op = "delete"
        return self

    # --- filters / modifiers (all no-ops that record) ---------------------
    def eq(self, column: str, value: Any) -> "FakeQuery":
        self._filters.append((column, value))
        return self

    def is_(self, column: str, value: Any) -> "FakeQuery":
        # PostgREST `.is_(col, "null")` (used by the bulk card revoke to match only
        # not-yet-revoked rows). Recorded as a filter so a test can assert it; the marker
        # value ("null") is recorded verbatim, the fake does no actual filtering.
        self._filters.append((column, value))
        return self

    def order(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        return self

    def single(self) -> "FakeQuery":
        self._single = True
        return self

    def maybe_single(self) -> "FakeQuery":
        self._single = True
        return self

    # --- terminal ---------------------------------------------------------
    def execute(self) -> FakeResponse:
        self._log.append(
            {
                "table": self._table,
                "op": self._op,
                "payload": self._payload,
                "filters": list(self._filters),
                "single": self._single,
            }
        )
        key = (self._table, self._op or "select")
        if key not in self._scripts:
            raise AssertionError(f"No scripted Supabase response for {key}")
        scripted = self._scripts[key]
        # A list of scripted responses is consumed in order (so a get-or-create
        # can return None on the first select and a row on the read-back).
        if isinstance(scripted, list) and scripted and isinstance(scripted[0], FakeResponse):
            return scripted.pop(0)
        if isinstance(scripted, FakeResponse):
            return scripted
        return FakeResponse(scripted)


class FakeRpc:
    """A recording RPC call: execute() returns the scripted response for the function.

    Mirrors client.rpc(fn, params).execute(). The function-call path (the Continuity
    Card token read goes through the SECURITY DEFINER function get_card_by_token) is
    scripted under the ("rpc", fn_name) key, alongside the table scripts.
    """

    def __init__(
        self,
        fn: str,
        params: Any,
        log: List[Dict[str, Any]],
        scripts: Dict[Tuple[str, str], Any],
    ):
        self._fn = fn
        self._params = params
        self._log = log
        self._scripts = scripts

    def execute(self) -> FakeResponse:
        self._log.append({"rpc": self._fn, "params": self._params})
        key = ("rpc", self._fn)
        if key not in self._scripts:
            raise AssertionError(f"No scripted Supabase response for {key}")
        scripted = self._scripts[key]
        if isinstance(scripted, list) and scripted and isinstance(scripted[0], FakeResponse):
            return scripted.pop(0)
        if isinstance(scripted, FakeResponse):
            return scripted
        return FakeResponse(scripted)


class FakeClient:
    """A fake Supabase client whose table(name) returns a recording FakeQuery.

    rpc(fn, params) returns a recording FakeRpc for the function-call path (the
    SECURITY DEFINER token read), scripted under the ("rpc", fn_name) key.
    """

    def __init__(self, scripts: Dict[Tuple[str, str], Any]):
        self.scripts = scripts
        self.calls: List[Dict[str, Any]] = []

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(name, self.calls, self.scripts)

    def rpc(self, fn: str, params: Any = None) -> FakeRpc:
        return FakeRpc(fn, params, self.calls, self.scripts)
