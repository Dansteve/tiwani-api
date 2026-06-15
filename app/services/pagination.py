"""Shared list-pagination helpers (the every-list-is-capped rule).

The api hard rule (HardRules/Api/SETUP.md): every list endpoint applies a CAPPED limit so
it can never read the table unboundedly, and a GROWABLE list also exposes a keyset cursor
and returns a `*Page {items, next_cursor}` shape (the /cards precedent). This module holds
the ONE clamp helper the list services share so the cap is not re-implemented per service
(the /cards list pre-dates this module and keeps its own private clamp; new code uses this).

`clamp_limit` is the single definition of "the effective, safe page size": a missing or
non-positive client limit falls back to the service's default, and a larger value is capped
at the service's hard maximum, so a client can never make the database read an unbounded
page. The per-list default and maximum stay with each service (the sizes differ: a growable
plans list pages in 50s, a bounded roster caps at a few hundred), this only enforces the
bound. Pure (no I/O), so it is unit-tested directly.
"""

from __future__ import annotations

from typing import Optional

# The safety cap for a naturally BOUNDED list (the every-list-is-capped rule). A bounded
# list (the six chapters, the active alerts, the plan tiers, the recipients, the children,
# the pending pulses, the roster, the shared-with-me, the snapshot reading window) is small
# in practice and exposes no cursor, but its DB read still gets a hard `.limit(...)` so a
# pathological row count (a bug, an abusive account) can never make the query or the
# response unbounded. It is set well above any legitimate bound (a Coordinator has a handful
# of recipients, a village a handful of members, a chapter at most one active alert), so it
# never truncates real data: it is purely the ceiling that stops a runaway read.
MAX_BOUNDED_ROWS = 500


def clamp_limit(limit: Optional[int], *, default: int, maximum: int) -> int:
    """The effective page size: the default when unset/non-positive, capped at the maximum.

    A None or non-positive `limit` (a client omitting it, or sending 0 / a negative) falls
    back to `default`; any larger value is capped at `maximum`. So the value returned is
    always in [1, maximum] (assuming 1 <= default <= maximum), which is the bound the
    service hands to the database `.limit(...)`: a client can never ask for an unbounded
    read. This is enforced HERE (the service), not only at the route's `Query(le=...)`, so
    an internal caller is bounded too.
    """
    if limit is None or limit <= 0:
        return default
    return min(limit, maximum)
