"""The calc seam: the round-after-multiplier and cap-at-5 behaviour of section 4.4.

THE CALC SEAM (Task 12 score-resolution decision). Product.md section 4.4 (the
AUTHORITATIVE engine spec) ROUNDS each dimension after the support multiplier
(step 2) and CAPS each dimension at 5 after every additive step (steps 2, 3, 4),
so the total stays in the 4 to 20 range. The Child Profile Tag doc's worked
example (Family Wedding) instead keeps DECIMALS after the multiplier and does NOT
cap each dimension at 5 (it reaches a total of 24.2). The PRD wins (the PRD-wins
rule in CLAUDE.md), so this module implements the round + cap. See the Task 12
"score resolution" decision (HardRules/Api/Modules/SeedData.md, Engine.md): the
alternative (keep decimals, a wider internal scale) can be swapped in by replacing
the two functions here WITHOUT touching the rest of the engine, because the engine
combines dimensions only through these two seam functions.

Rounding mode is fixed to round-half-up (ROUND_HALF_UP), computed on an EXACT
Decimal product (Decimal(base) * Decimal(str(multiplier))), not on the raw binary
float, so a value that lands on a .5 boundary always rounds up and a float
artefact (3 * 1.2 == 3.5999999999999996) cannot perturb the result. With the
current seed multipliers (1.0, 1.2, 1.4) on whole base scores 1 to 5 no product
lands exactly on .5, so round-half-up and round-half-even agree on every reachable
input; the mode is pinned anyway so a future seed multiplier change cannot
silently shift behaviour. Pinned in tests (tests/test_engine_lce.py).

The cap value is the seed's MAX_BASE_SCORE (5), imported, not inlined: the engine
reads bounds from the seed/model layer, never a hardcoded score (the SeedData.md
hard rule; a pytest guard, tests/test_seed.py, asserts the LCE source hardcodes no
numeric score >= 2).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models.seed import MAX_BASE_SCORE


def apply_multiplier_and_round(base_value: int, multiplier: float) -> int:
    """Multiply a base dimension score by the support multiplier and round (step 2).

    The section 4.4 step 2 round: an EXACT Decimal product rounded half-up to a
    whole number. NOT capped here (the caller caps with cap_dimension after the
    multiply); kept separate so the seam's two behaviours, the round and the cap,
    are each replaceable on their own for the Task 12 alternative.
    """
    product = Decimal(base_value) * Decimal(str(multiplier))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cap_dimension(value: int) -> int:
    """Cap a single dimension at the maximum score (section 4.4: cap each at 5).

    Applied after EVERY additive step (the multiplier in step 2, the permanent
    tags in step 3, the today flags in step 4), so a dimension can never exceed
    MAX_BASE_SCORE. The cap is silent (the Coordinator never sees "capped",
    section 4.4 step 4).
    """
    return min(value, MAX_BASE_SCORE)
