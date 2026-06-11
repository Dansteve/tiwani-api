"""Per-dimension one-line explanations (section 4.4 step 10).

The plan returns one short, plain-English sentence per dimension explaining why it
scored where it did, so the Coordinator understands the number without being told
what to do. NON-CLINICAL by rule (Product.md section 4.9 governs all copy): no
diagnosis, symptom, condition, or treatment language. The sentences describe the
ACTIVITY's demand and, where a profile or today factor raised a dimension, name
that factor in everyday words ("loud, busy settings", "changes to the usual
routine", "a tiring day"), never a clinical label.

Mechanism: each sentence is built from (a) a band phrase for the final dimension
score (low / moderate / high pressure) and (b) the dimension's plain meaning, with
an optional clause naming the strongest contributing factor when the profile tags
or today flags lifted that dimension. The factor clause is chosen from a fixed,
governed phrase map keyed by tag code (the same five families the engine reads),
so the copy is deterministic and stays inside the non-clinical bounds. No free
text from the user is ever echoed here.
"""

from __future__ import annotations

from typing import Dict, List

from app.engines.lce.strategies import HIGH_DIMENSION_THRESHOLD
from app.models.seed import MIN_BASE_SCORE, Dimension

# The bands a final dimension score reads as, in plain words: at or above
# HIGH_DIMENSION_THRESHOLD (the section 4.4 step 7 "high-scoring dimensions (>= 3)"
# cut, imported) is high; above the base-score floor (MIN_BASE_SCORE) but below the
# high cut is moderate; at the floor it is low. Named bounds, never magic numbers
# inside the sentences (the SeedData.md hard rule on the LCE source).

# Plain, non-clinical meaning of each dimension (what the pressure is ABOUT).
_DIMENSION_MEANING: Dict[Dimension, str] = {
    Dimension.TEMPORAL: "the timing, waiting and how long it runs",
    Dimension.SENSORY: "the noise, lights, crowds and other sensory load",
    Dimension.LOGISTICAL: "the practical planning, equipment and number of steps",
    Dimension.HUMAN: "the social side, new people and being around others",
}

# A governed, non-clinical phrase for the strongest factor that lifted a dimension,
# keyed by tag code. Only the tags that carry a pressure modifier appear here. The
# wording is everyday language a parent uses, never a clinical term (section 4.9).
_FACTOR_PHRASE: Dict[str, str] = {
    # Sensory (SN-)
    "SN-NOISE": "this tends to be a loud setting",
    "SN-CROWD": "this tends to be a busy, crowded setting",
    "SN-LIGHT": "the lighting can be bright or harsh",
    "SN-TEXTURE": "there can be unfamiliar textures",
    "SN-SMELL": "there can be strong smells",
    "SN-TASTE": "food or eating is part of it",
    "SN-TOUCH": "there can be a lot of physical closeness",
    "SN-TEMP": "the temperature may be hard to predict",
    "SN-UNPRED": "the surroundings can be unpredictable",
    # Transitions (TR-)
    "TR-LOC": "it involves moving between places",
    "TR-SWITCH": "it means switching between activities",
    "TR-END": "it means ending something enjoyable",
    "TR-NEW": "it is something new or unfamiliar",
    "TR-CHANGE": "plans here can change at short notice",
    "TR-WAIT": "there can be a lot of waiting",
    # Communication (CM-)
    "CM-NONVERBAL": "communicating in the moment takes more support",
    "CM-AAC": "communication aids need managing here",
    "CM-ECHO": "communicating in the moment takes more support",
    # Recovery (RC-)
    "RC-MOD": "there is little recovery time afterwards",
    "RC-EXT": "there is very little recovery time afterwards",
    "RC-VAR": "recovery time afterwards is hard to predict",
    # Triggers (TG-, today flags)
    "TG-HUNGER": "it falls near a meal or snack time today",
    "TG-FATIGUE": "it is a tired day today",
    "TG-ILL": "they are unwell today",
    "TG-ANXIETY": "it is an unsettled day today",
    "TG-MEDS": "it is a medication-change period today",
    "TG-HOME": "there is a lot of change at home today",
}


def _band_phrase(score: int) -> str:
    """The pressure band for a final dimension score, in plain words."""
    if score >= HIGH_DIMENSION_THRESHOLD:
        return "is high"
    if score > MIN_BASE_SCORE:
        return "is moderate"
    return "is low"


def build_dimension_explanations(
    final_scores: Dict[Dimension, int],
    permanent_tags: List[str],
    today_flags: List[str],
    used_chapter_average: bool,
) -> Dict[str, str]:
    """One non-clinical sentence per dimension explaining its final score.

    final_scores is the capped per-dimension result (section 4.4 step 4 output).
    permanent_tags and today_flags are the profile tags and today flags that fed
    steps 3 and 4; the strongest matching factor for a dimension is named in
    everyday language. used_chapter_average notes a custom activity (the plan says
    the scores are an estimate from similar activities). Returns a dict keyed by
    the dimension string value (temporal/sensory/logistical/human), the shape the
    PreparationPlan carries.
    """
    explanations: Dict[str, str] = {}
    all_factors = list(permanent_tags) + list(today_flags)
    for dimension, score in final_scores.items():
        sentence = f"This {_dimension_label(dimension)} pressure {_band_phrase(score)}"
        factor = _strongest_factor_for(dimension, score, all_factors)
        if factor is not None:
            sentence += f", because {factor}"
        sentence += f" ({_DIMENSION_MEANING[dimension]})."
        if used_chapter_average:
            sentence += (
                " This is an estimate from similar activities, as this one is custom."
            )
        explanations[dimension.value] = sentence
    return explanations


def _dimension_label(dimension: Dimension) -> str:
    """The human label for a dimension used inside a sentence."""
    return dimension.value


def _strongest_factor_for(
    dimension: Dimension, score: int, factor_codes: List[str]
) -> str | None:
    """The plain phrase for the strongest factor that lifted this dimension.

    Only named when the dimension actually carries pressure (above the floor) and
    a contributing tag/flag affects it; a low dimension gets no factor clause. The
    first matching factor in the (permanent then today) order is used, which keeps
    the sentence deterministic.
    """
    if score <= MIN_BASE_SCORE:
        return None
    from app.engines.lce.engine import dimensions_for_tag  # local import avoids cycle

    for code in factor_codes:
        if dimension in dimensions_for_tag(code) and code in _FACTOR_PHRASE:
            return _FACTOR_PHRASE[code]
    return None
