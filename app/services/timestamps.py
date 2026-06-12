"""Shared timestamptz parsing for the data services.

Supabase / PostgREST delivers a timestamptz as an ISO-ish string, but in two shapes that
Python 3.9's strict datetime.fromisoformat rejects:
  1. an HOURS-ONLY offset ("+00", not "+00:00") in the Postgres TEXT form, and
  2. a FRACTIONAL-SECOND part whose digit count is not 0/3/6: PostgreSQL's to_json (what
     PostgREST / supabase-py actually returns over the wire) TRIMS trailing zeros, so a
     microsecond value of 210110 serialises as ".21011" (5 digits) and .100000 as ".1"
     (1 digit), while 3.9's fromisoformat accepts ONLY 0, 3, or 6 fractional digits.
Either shape makes a naive fromisoformat raise, so the caller gets None. That is harmless
where None is tolerated, but it BREAKS any read that feeds the value into a REQUIRED
datetime field (e.g. CardSummary.created_at -> a 500 on a single odd-microsecond card).
This normaliser makes the Supabase value parseable on 3.9 so there is ONE correct parser
across the services (it previously lived as a copy-pasted _parse_dt in six of them).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

# A trailing UTC offset with NO colon: "+00" / "-05" (hours only) or "+0000" / "-0530"
# (hours+minutes). Postgres emits the hours-only form; both are normalised to "+HH:MM".
_COLONLESS_OFFSET = re.compile(r"([+-]\d{2})(\d{2})?$")

# The fractional-second run (the only ".digits" in an ISO timestamp: the date uses dashes,
# the time colons, the offset +/- and a colon). Normalised to exactly 6 digits for 3.9.
_FRACTIONAL_SECONDS = re.compile(r"\.(\d+)")


def parse_timestamptz(value: Any) -> Optional[datetime]:
    """Parse a Supabase timestamptz (Postgres/ISO string or datetime) to an aware datetime, or None.

    Accepts the value as it arrives from PostgREST: a string (the Postgres text form, or an
    ISO string, possibly with a trailing 'Z'), an already-parsed datetime, or None. A naive
    result is assumed UTC. Returns None only for None or a genuinely unparseable string.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00").replace(" ", "T")
        # Give a colon-less trailing offset its minutes so 3.9's fromisoformat accepts it
        # ("+00" -> "+00:00", "+0530" -> "+05:30"). A value already in "+HH:MM" form, or a
        # naive value with no offset, is left unchanged (the regex requires a sign + digits
        # at the very end with no colon).
        text = _COLONLESS_OFFSET.sub(lambda m: m.group(1) + ":" + (m.group(2) or "00"), text)
        # Pad/truncate the fractional seconds to exactly 6 digits: PostgreSQL's to_json trims
        # trailing zeros (".21011", ".1"), but 3.9's fromisoformat accepts only 0/3/6 digits.
        text = _FRACTIONAL_SECONDS.sub(lambda m: "." + (m.group(1) + "000000")[:6], text)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None
