"""The SHORT human-typable JOIN CODE for a Shared-Child invite (the 2026-06-13 CTO +
researcher board verdict, governance/Sprints/Backlog.md, the "short typed join code" row).

The opaque invite token (0015) is ~256-bit and impossible to type. This module is the ONE
shared helper for the short code a helper can TYPE instead: generation, display formatting,
and input normalization. It is pure (no I/O, no DB, no scoring), deterministic except for the
CSPRNG draw, and table-tested (tests/test_join_code.py).

The board's bar for a credential to a vulnerable child's village:
  - Crockford base32 (alphabet 0123456789ABCDEFGHJKMNPQRSTVWXYZ, which EXCLUDES I, L, O, U):
    I/L/O are visually confusable with 1/1/0 and U is dropped to avoid an accidental obscene
    word. This is the standard human-facing base32 (Douglas Crockford's spec).
  - 10 chars from secrets (a CSPRNG): 32 ** 10 == 2 ** 50, so ~50 bits of entropy. The board
    NO-GO is 8 chars / 40-bit; do NOT shorten below 10. A sub-64-bit secret is only safe
    BECAUSE the redeem is email-bound (the real second factor) AND throttled (app/rate_limit).
  - DISPLAY as XXXXX-XXXXX (a single cosmetic dash splitting the 10 chars 5+5), easy to read
    aloud and to type. The dash is NOT stored and NOT significant.
  - STORE / LOOK UP the NORMALIZED form: uppercase, no dashes/spaces. normalize_join_code maps
    the Crockford decode aliases (I and L -> 1, O -> 0) so a human who mistypes a 1 as an I, or
    a 0 as an O, is forgiven, and rejects anything still outside the alphabet.

Generation is for code we MINT (so it only ever draws from the canonical alphabet, never an
alias). Normalization is for code a human TYPES back (so it forgives the aliases). The two are
deliberately asymmetric: we never emit an I/L/O/U, but we accept a typed I/L as 1 and O as 0.
"""

from __future__ import annotations

import secrets

# Crockford base32: the canonical 32-symbol alphabet, excluding I, L, O, U. This is the set we
# DRAW from when generating a code, so an emitted code never contains a confusable letter.
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# The number of code characters. 10 -> 32**10 == 2**50 (~50 bits): the board's floor (8/40-bit
# is a NO-GO). Two display groups of 5.
JOIN_CODE_LENGTH = 10
_GROUP = 5

# The Crockford INPUT decode aliases (applied only when normalizing a TYPED code, never when
# generating): a human cannot tell some letters from some digits, so accept the letter as the
# digit. I and L read as 1; O reads as 0. (U is not aliased: it is simply not in the alphabet,
# so a typed U is rejected as out-of-alphabet, which is correct because we never emit a U.)
_INPUT_ALIASES = {
    "I": "1",
    "L": "1",
    "O": "0",
}

# Characters stripped from a typed code as cosmetic separators before normalization.
_SEPARATORS = (" ", "-", "\t", "\n", "\r")


class InvalidJoinCodeError(ValueError):
    """Raised when a typed string cannot be normalized to a valid join code.

    A normal user-input error (the route maps it to the SAME generic 400 as every other
    redeem failure, so it is no oracle), not a programming error: the typed code contained a
    character that is not in the Crockford alphabet (after alias mapping), or it was the wrong
    length. The exception carries no detail that distinguishes WHY for the end user.
    """


def generate_join_code() -> str:
    """A fresh NORMALIZED join code: JOIN_CODE_LENGTH Crockford chars from a CSPRNG.

    Uses secrets.choice (a CSPRNG) over the canonical alphabet, so every character is in
    0123456789ABCDEFGHJKMNPQRSTVWXYZ (never an I/L/O/U). Returns the NORMALIZED form (uppercase,
    no dashes) ready to store; call format_join_code for the XXXXX-XXXXX display. ~50 bits of
    entropy at length 10. The caller (the sharing service) stores this verbatim and may retry
    on the vanishingly-rare active-code collision the DB partial-unique index rejects.
    """
    return "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


def format_join_code(normalized: str) -> str:
    """The display form XXXXX-XXXXX of a normalized code (a single cosmetic dash, 5+5).

    Splits the normalized code into groups of _GROUP joined by a dash, purely for legibility
    (reading aloud, typing). The dash is cosmetic: normalize_join_code strips it on the way
    back in. A code that is not the expected length is grouped best-effort (so a caller that
    formats an unexpected value does not crash), but generate_join_code always yields the exact
    length.
    """
    s = normalized.strip().upper()
    return "-".join(s[i : i + _GROUP] for i in range(0, len(s), _GROUP)) if s else s


def normalize_join_code(typed: str) -> str:
    """Normalize a TYPED join code to the canonical stored form, or raise InvalidJoinCodeError.

    Case- and dash-insensitive and Crockford-decode-correct, so a human's reasonable mistyping
    is forgiven:
      1. uppercase and strip the cosmetic separators (dashes, spaces, tabs/newlines),
      2. map the Crockford input aliases (I and L -> 1, O -> 0), so a 1 typed as I/L or a 0
         typed as O still resolves,
      3. reject (InvalidJoinCodeError) anything still outside the Crockford alphabet, or the
         wrong length.
    The returned string is exactly what the mint stored (uppercase, no dashes, alias-resolved),
    so the by-code lookup compares like-for-like. The route maps the raised error to the SAME
    generic 400 as every other redeem failure (no oracle).
    """
    if typed is None:
        raise InvalidJoinCodeError("join code is required")

    s = typed.strip().upper()
    for sep in _SEPARATORS:
        s = s.replace(sep, "")
    s = "".join(_INPUT_ALIASES.get(ch, ch) for ch in s)

    if len(s) != JOIN_CODE_LENGTH:
        raise InvalidJoinCodeError("join code is the wrong length")
    if any(ch not in CROCKFORD_ALPHABET for ch in s):
        raise InvalidJoinCodeError("join code has a character outside the alphabet")
    return s
