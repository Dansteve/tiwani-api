"""Situated-strategy templates + enrichment copy (LCEEngineAddendum.md 2, 5).

The GOVERNED, non-clinical copy the Fusion Layer turns into situated strategies, and
the value-first enrichment questions the Specificity Gate asks when a Plan cannot yet
be made specific. It lives in the seed layer (authored, versioned data the engine
reads) for two reasons:
  - the pure Fusion Layer (app/engines/lce/fusion.py) may not hold copy or a numeric
    literal >= 2 (the LCE no-hardcoded-score guard, tests/test_seed.py), so the copy
    lives here and the engine imports build_situated_sentence / build_enrichment_question;
  - this copy is validated NON-CLINICAL on seed load through the SAME shared guard the
    alert and Continuity Card builders use (app/engines/alerts/guard, Product.md 4.9),
    so a future copy edit cannot slip a prohibited clinical word past the load.

GOVERNED-COPY GATE (LCEEngineAddendum.md "Governed-copy note", BuildPlan-PRDv2.md
Wave 2). The situated-strategy templates and the enrichment questions are new
care-adjacent, user-facing copy. They pass the non-clinical bar here, but the
PSYCHIATRIST copy sign-off still gates PRODUCTION enablement. Local / beta builds
(the Wave-1 demonstrable slice) may use the templates below pending that sign-off;
nothing in this slice deploys or flips a production flag.

A situated-strategy template is ONE sentence carrying the ACTION, the SPECIFIC
moment, and the REASON (the child's pressure point). Templates are keyed
template[tag][moment_type]; moment_type is the moment id (e.g. "arrival"). Each tag
has a "_default" used for any moment, with optional per-moment overrides. {child}
interpolates the care recipient's name; {moment} interpolates the moment label.
"""

from __future__ import annotations

from typing import Dict, List

# The version label travels with the copy (SeedData.md: seed content is versioned; a
# copy change is a new version, and it re-clears the psychiatrist sign-off).
SITUATED_TEMPLATES_VERSION = "situated_templates_v1"

# Human labels for the tag codes, shown as the enrichment tap options (LCEEngineAddendum
# section 5 step 2). Plain, everyday words a carer uses, never a clinical term.
TAG_LABEL: Dict[str, str] = {
    "SN-NOISE": "Loud sounds",
    "SN-CROWD": "Busy, crowded spaces",
    "SN-LIGHT": "Bright or harsh light",
    "SN-TEXTURE": "Unfamiliar textures",
    "SN-SMELL": "Strong smells",
    "SN-TASTE": "Food and eating",
    "SN-TOUCH": "Unexpected touch",
    "SN-TEMP": "Heat or cold",
    "SN-UNPRED": "Not knowing what comes next",
    "TR-LOC": "Moving between places",
    "TR-SWITCH": "Switching between activities",
    "TR-END": "Ending something they enjoy",
    "TR-NEW": "New or unfamiliar things",
    "TR-CHANGE": "Last-minute changes of plan",
    "TR-WAIT": "Waiting around",
    "RC-MOD": "Little recovery time after",
    "RC-EXT": "Very little recovery time after",
    "RC-VAR": "Unpredictable recovery time",
    "CM-NONVERBAL": "Communicating in the moment",
    "CM-AAC": "Managing a communication aid",
    "CM-ECHO": "Being understood in the moment",
}

# The situated-strategy templates: template[tag]["_default" | moment_id] -> a sentence.
# The "_default" is used for any moment; a moment id (e.g. "arrival", "assembly")
# overrides it where a more specific line reads better. Only tags that concentrate
# pressure carry a template; any other loading tag uses _GENERIC_TEMPLATE.
SITUATED_TEMPLATES: Dict[str, Dict[str, str]] = {
    "SN-CROWD": {
        "_default": (
            "Get to {moment} a little early and head for a quieter corner, since "
            "busy, crowded moments are a lot for {child}."
        ),
        "arrival": (
            "Arrive before the crowd builds and find a calmer spot for {moment}, "
            "since busy arrivals are a lot for {child}."
        ),
    },
    "SN-NOISE": {
        "_default": (
            "Have ear defenders or headphones ready for {moment}, since loud sounds "
            "are a lot for {child}."
        ),
        "assembly": (
            "Bring ear defenders for {moment} and sit near an exit, since the sound "
            "and light of a full hall are a lot for {child}."
        ),
    },
    "SN-LIGHT": {
        "_default": (
            "Have sunglasses or a cap ready for {moment} and pick a spot away from "
            "the brightest lights, since harsh light is a lot for {child}."
        ),
    },
    "SN-TEXTURE": {
        "_default": (
            "Bring a familiar comfort item to {moment}, since unfamiliar textures "
            "are a lot for {child}."
        ),
    },
    "SN-SMELL": {
        "_default": (
            "Plan a quick way to step outside during {moment}, since strong smells "
            "are a lot for {child}."
        ),
    },
    "SN-TASTE": {
        "_default": (
            "Bring a safe, familiar food to {moment}, so {child} has something they "
            "trust when eating is part of it."
        ),
    },
    "SN-TOUCH": {
        "_default": (
            "Let {child} know before any hands-on part of {moment} and ask for it to "
            "go slowly, since unexpected touch is a lot for them."
        ),
        "chair": (
            "Ask the dentist to explain and show each step of {moment} before it "
            "happens, since unexpected touch is a lot for {child}."
        ),
    },
    "SN-UNPRED": {
        "_default": (
            "Walk {child} through what {moment} will be like beforehand, since not "
            "knowing what comes next is a lot for them."
        ),
    },
    "TR-WAIT": {
        "_default": (
            "Bring something to do during {moment}, since open waiting is hard for "
            "{child}."
        ),
    },
    "TR-LOC": {
        "_default": (
            "Give {child} a heads-up before {moment}, since moving between places is "
            "hard for them."
        ),
    },
    "TR-SWITCH": {
        "_default": (
            "Give a short warning before {moment}, since switching between activities "
            "is hard for {child}."
        ),
    },
    "TR-END": {
        "_default": (
            "Signal that {moment} is coming a few minutes ahead, since ending "
            "something enjoyable is hard for {child}."
        ),
    },
    "TR-CHANGE": {
        # No {moment} in the body: this template also fires on sudden-disruption
        # moments (a change already happened), where "keep {moment} predictable" reads
        # wrong (doctor pre-screen m3). The moment label still heads the group.
        "_default": (
            "When this happens, keep things as predictable as you can and name the "
            "change out loud, since last-minute changes are a lot for {child}."
        ),
    },
    "RC-MOD": {
        "_default": (
            "Protect some quiet time after {moment}, since {child} has little room to "
            "recover before the next thing."
        ),
    },
    "RC-EXT": {
        "_default": (
            "Keep the rest of the day light after {moment}, since {child} needs a "
            "long, protected wind-down."
        ),
    },
    "RC-VAR": {
        "_default": (
            "Leave the time after {moment} flexible, since how long {child} needs to "
            "recover varies."
        ),
    },
}

# The fallback when a loading tag has no authored template: still situated to the
# moment, still non-clinical, never generic.
_GENERIC_TEMPLATE = (
    "A little preparation for {moment} helps {child} take part more comfortably."
)

# The value-first enrichment question per pressure dimension (LCEEngineAddendum
# section 5 step 2): it improves the Plan NOW, it does not "collect data". Warm,
# non-clinical, and it names the dimension in everyday words. {child} interpolates
# the recipient's name.
ENRICHMENT_QUESTIONS: Dict[str, str] = {
    "sensory": (
        "This can be a lot of sound, light, smell and unexpected touch. Which of "
        "these is hardest for {child}?"
    ),
    "temporal": (
        "This can involve waiting, and switching between things at short notice. "
        "Which of these is hardest for {child}?"
    ),
    "logistical": (
        "This can mean moving between places and juggling a few practical steps. "
        "Which of these is hardest for {child}?"
    ),
    "human": (
        "This can mean being around new people and communicating on the spot. Which "
        "of these is hardest for {child}?"
    ),
}


def build_situated_sentence(
    loaders: List[str], moment_id: str, moment_label: str, child_name: str
) -> str:
    """One situated-strategy sentence for a moment's active loading tags.

    The primary tag (the first active loader, in the moment's loads order) chooses
    the template; template[tag][moment_id] wins over template[tag]["_default"], and a
    tag with no template uses the generic line. {child} and {moment} are interpolated.
    Deterministic: the same loaders + moment + name always yield the same sentence.
    """
    primary = loaders[0] if loaders else ""
    per_tag = SITUATED_TEMPLATES.get(primary, {})
    template = per_tag.get(moment_id) or per_tag.get("_default") or _GENERIC_TEMPLATE
    name = child_name.strip() if child_name and child_name.strip() else "your child"
    return template.format(child=name, moment=moment_label)


def build_enrichment_question(dimension: str, child_name: str) -> str:
    """The value-first enrichment question for a pressure dimension (section 5)."""
    name = child_name.strip() if child_name and child_name.strip() else "your child"
    question = ENRICHMENT_QUESTIONS.get(
        dimension,
        "Which part of this is hardest for {child}?",
    )
    return question.format(child=name)


def all_copy_strings() -> List[str]:
    """Every authored copy string, for the seed load's non-clinical guard.

    The loader scans these with the shared prohibited-clinical-words guard so a future
    edit that slips a clinical word in fails the seed load, not only a unit test.
    """
    strings: List[str] = list(TAG_LABEL.values())
    for per_tag in SITUATED_TEMPLATES.values():
        strings.extend(per_tag.values())
    strings.append(_GENERIC_TEMPLATE)
    strings.extend(ENRICHMENT_QUESTIONS.values())
    return strings
