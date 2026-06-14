"""Table-driven tests for the short typable JOIN CODE helper (app/engines/sharing/join_code.py).

The join code is a CREDENTIAL to a vulnerable child's village (the 2026-06-13 board verdict),
so its generation + normalization are pinned exactly:
  - GENERATION: every emitted code is Crockford base32 (alphabet membership, NO I/L/O/U), the
    exact length (10 chars / ~50 bits, the board floor; 8/40-bit is a NO-GO), and the CSPRNG
    draw spreads across the alphabet.
  - DISPLAY: the cosmetic XXXXX-XXXXX form round-trips through normalization unchanged.
  - NORMALIZATION: case- and dash-insensitive, and Crockford-decode-correct (I -> 1, L -> 1,
    O -> 0), rejecting anything still outside the alphabet or the wrong length. A typed code
    with its dashes / lower case / aliases resolves to exactly the stored form.
"""

from __future__ import annotations

import pytest

from app.engines.sharing.join_code import (
    CROCKFORD_ALPHABET,
    JOIN_CODE_LENGTH,
    InvalidJoinCodeError,
    format_join_code,
    generate_join_code,
    normalize_join_code,
)

# The excluded letters: the whole point of Crockford base32 for human input.
_EXCLUDED = ("I", "L", "O", "U")


# --- the alphabet itself ----------------------------------------------------------------------

def test_alphabet_is_crockford_32_symbols_without_iluo():
    assert len(CROCKFORD_ALPHABET) == 32
    assert len(set(CROCKFORD_ALPHABET)) == 32  # no duplicates
    for ch in _EXCLUDED:
        assert ch not in CROCKFORD_ALPHABET
    # The canonical Crockford alphabet, verbatim.
    assert CROCKFORD_ALPHABET == "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def test_length_is_the_board_floor_of_ten():
    # 32 ** 10 == 2 ** 50; the board NO-GO is 8 chars / 40-bit, so the floor is 10.
    assert JOIN_CODE_LENGTH == 10
    assert 32 ** JOIN_CODE_LENGTH == 2 ** 50


# --- generation -------------------------------------------------------------------------------

def test_generate_is_exact_length_and_only_alphabet_chars():
    for _ in range(500):  # many draws: every char must be in-alphabet, never an excluded letter
        code = generate_join_code()
        assert len(code) == JOIN_CODE_LENGTH
        assert all(ch in CROCKFORD_ALPHABET for ch in code)
        assert all(ch not in _EXCLUDED for ch in code)
        assert code == code.upper()  # normalized (uppercase) and no dashes
        assert "-" not in code


def test_generate_spreads_across_the_alphabet_via_the_csprng():
    # Not a randomness proof, just a smoke check that the CSPRNG draw is not stuck on one symbol:
    # over many codes we should see a large fraction of the 32 symbols appear.
    seen: set[str] = set()
    for _ in range(500):
        seen.update(generate_join_code())
    assert len(seen) >= 28  # nearly the whole alphabet shows up across 5000 chars
    assert not (seen & set(_EXCLUDED))


def test_generated_codes_are_not_trivially_repeated():
    # 50 bits of entropy: 1000 draws should essentially never collide. (A collision here would
    # signal the generator lost its entropy, e.g. a fixed seed.)
    codes = [generate_join_code() for _ in range(1000)]
    assert len(set(codes)) == len(codes)


# --- display formatting -----------------------------------------------------------------------

def test_format_is_xxxxx_dash_xxxxx():
    formatted = format_join_code("ABCDE12345")
    assert formatted == "ABCDE-12345"


def test_format_then_normalize_round_trips_to_the_same_stored_code():
    for _ in range(200):
        code = generate_join_code()
        assert normalize_join_code(format_join_code(code)) == code


# --- normalization: the forgiving, Crockford-correct input path -------------------------------

def test_normalize_is_case_insensitive():
    assert normalize_join_code("abcde12345") == "ABCDE12345"


def test_normalize_strips_dashes_and_spaces():
    assert normalize_join_code("ABCDE-12345") == "ABCDE12345"
    assert normalize_join_code("  ABCDE 12345 ") == "ABCDE12345"
    assert normalize_join_code("AB-CD-E1-23-45") == "ABCDE12345"


@pytest.mark.parametrize(
    "typed,expected",
    [
        # I and L decode to 1 (visually confusable). Here 8 valid chars + two aliased letters.
        ("2345678 9IL", "23456789" + "11"),
        ("234567890I", "2345678901"),
        ("234567890L", "2345678901"),
        # O decodes to 0.
        ("23456789OO", "2345678900"),
        # lower-case aliases too (uppercased first, then mapped).
        ("23456789il", "2345678911"),
        ("23456789oo", "2345678900"),
        # a realistic mistype: the displayed XXXXX-XXXXX form, lowercased, with an O-for-0 and
        # an I-for-1 and an l-for-1 typed in (10 code chars: 23abc-do1il -> 23ABCD0111).
        ("23abc-do1il", "23ABCD0111"),
    ],
)
def test_normalize_maps_crockford_input_aliases(typed, expected):
    assert normalize_join_code(typed) == expected


def test_normalize_rejects_a_character_outside_the_alphabet():
    # U is never emitted and is not aliased, so a typed U is rejected (out of alphabet).
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code("2345678 9UU")
    # A symbol char is rejected too.
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code("2345678 9$%")


def test_normalize_rejects_the_wrong_length():
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code("ABCDE")  # too short
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code("ABCDE1234567890")  # too long


def test_normalize_rejects_empty_or_none():
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code("")
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code("   ---  ")
    with pytest.raises(InvalidJoinCodeError):
        normalize_join_code(None)  # type: ignore[arg-type]


def test_a_generated_code_normalizes_to_itself():
    for _ in range(200):
        code = generate_join_code()
        assert normalize_join_code(code) == code
