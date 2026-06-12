"""GOVERNED COPY for the Village Delegation Hub (Docs/FeatureDecisions.md, refinement 6).

The user-facing Hub copy is GOVERNED: every string below is WARM and CAPACITY-FRAMED,
NON-clinical, NON-surveillance, and never leaks an internal role label. None of it may be
paraphrased, reworded, or extended without the product owner AND the psychiatrist sign-off
that gates the launch (Task 12). It is the Hub's analogue of app/engines/alerts/copy.py.

Each string is addressed by a STABLE COPY-KEY (the keys in COPY below). The api returns
copy-keys plus any rendered text (the app may also localise from the key), and the
record-consent flow stores CONSENT_TEXT verbatim, so the consent record shows exactly what
the Coordinator agreed to. The ONLY runtime substitution is {name} -> the care
recipient's first name (the Continuity Card ceiling: first name only, never more).

THE VOICE (the board's direction):
  - The Hub helps a Coordinator ASK for specific, bounded help and a neighbour OFFER it.
    Specific offers convert (carers under-ask out of reciprocity and shame), so the copy
    nudges a clear what / when / where, warmly, never as a demand.
  - It frames a helper as someone lending a hand to the FAMILY, never as a watcher of a
    person: no "monitor / track / case / subject / surveillance" (guard.py bars them).
  - It says "you", "[name]'s village", "the family", never "viewer" / "owner" (the RBAC
    role labels stay internal; guard.py bars them as user-facing words).

Every string in this module passes the Village Hub guard (app/engines/village/guard.py);
render() re-checks at emit time and the guard test pins it over all copy.
"""

from __future__ import annotations

from typing import Dict, List

from app.engines.village.guard import assert_clean

# The single runtime substitution: the recipient's FIRST name (the Card ceiling).
NAME_TOKEN = "{name}"


# The governed copy, by stable copy-key. Grouped by surface. {name} is resolved at render
# time. Keep the keys stable: the app and the consent record reference them.
COPY: Dict[str, str] = {
    # --- the per-recipient consent text (the Art. 9 gate, stored verbatim) -------------
    # Recorded by the owner before any need can be broadcast. Capacity-framed, names the
    # purpose plainly, no clinical or surveillance words, no role labels.
    "consent.share_with_village": (
        "I confirm I have the authority to share what {name}'s village needs to help with "
        "a specific task, when and where it happens, and who to reach on the day. I can "
        "withdraw this at any time, and helpers only ever see the task they are helping "
        "with."
    ),

    # --- posting a need (the Coordinator asks) -----------------------------------------
    "need.post_intro": (
        "Ask {name}'s village for a hand with one specific thing. A clear ask, with a time "
        "and a place, is the easiest kind to say yes to."
    ),
    "need.post_what_label": "What would help?",
    "need.post_when_label": "When is it?",
    "need.post_where_label": "Where does it happen?",
    "need.post_contact_label": "Who should they reach on the day?",
    "need.posted_confirmation": (
        "Shared with {name}'s village. You will see who offers to help, and you confirm "
        "before anything is set."
    ),

    # --- the village sees the broadcast (the helper) -----------------------------------
    "need.board_intro": (
        "Here is where {name}'s village can lend a hand. Offer for anything you are able "
        "to, and the family will confirm with you."
    ),
    "need.open_badge": "Open to help",
    "need.claimed_badge": "Someone has offered",
    "need.confirmed_badge": "Confirmed with the family",

    # --- claiming (the helper offers) --------------------------------------------------
    "need.claim_action": "Offer to help",
    "need.claim_confirmation": (
        "Thank you for offering. The family will confirm, and then you will see the "
        "details for the day. You can step back any time if your plans change."
    ),
    "need.claim_taken": (
        "Someone in the village just offered for this one. Thank you, there will be other "
        "ways to help."
    ),

    # --- the owner confirms ------------------------------------------------------------
    "need.confirm_action": "Confirm this offer",
    "need.confirmed_confirmation": (
        "Confirmed. They can now see the details for the day, and you will both know the "
        "plan is set."
    ),

    # --- marking done (the helper closes the loop) -------------------------------------
    "need.done_action": "Mark as done",
    "need.done_confirmation": (
        "Done, thank you. That is one less thing for the family to hold."
    ),

    # --- dropping (the helper steps back; auto re-broadcast) ---------------------------
    "need.drop_action": "Step back from this",
    "need.drop_confirmation": (
        "No problem at all. We have let the rest of {name}'s village know it is open again, "
        "so someone else can pick it up."
    ),

    # --- the owner cancels -------------------------------------------------------------
    "need.cancel_action": "Cancel this ask",
    "need.cancelled_confirmation": (
        "Cancelled. The village will no longer see this one."
    ),

    # --- the roster (who is in the village) --------------------------------------------
    "roster.title": "{name}'s village",
    "roster.intro": (
        "The people you have invited to lend {name} a hand. You can add or remove anyone, "
        "any time."
    ),
}

# The copy-keys the api surfaces for each Hub action's result, so the app shows the right
# warm confirmation. The route names these in its response (the copy-key contract).
RESULT_KEY_BY_ACTION: Dict[str, str] = {
    "posted": "need.posted_confirmation",
    "claimed": "need.claim_confirmation",
    "confirmed": "need.confirmed_confirmation",
    "done": "need.done_confirmation",
    "dropped": "need.drop_confirmation",
    "cancelled": "need.cancelled_confirmation",
}


def render(key: str, *, name: str = "") -> str:
    """The governed string for a copy-key, {name} resolved, guarded at emit time.

    Substitutes the recipient's first name (the only allowed substitution) and runs the
    Village Hub guard over the result, so a prohibited word can never leave the engine. A
    blank name falls back to a neutral phrase so the sentence still reads.
    """
    if key not in COPY:
        raise KeyError(f"unknown village copy key: {key!r}")
    safe_name = name.strip() or "the family"
    text = COPY[key].replace(NAME_TOKEN, safe_name)
    assert_clean(text)
    return text


def consent_text(*, name: str = "") -> str:
    """The verbatim per-recipient consent text (stored on record_village_consent).

    The exact governed text the Coordinator agrees to and that is persisted verbatim in
    recipient_village_consent.consent_text, so the audit record shows precisely what was
    agreed. {name} resolved; guarded.
    """
    return render("consent.share_with_village", name=name)


def result_copy_key(action: str) -> str:
    """The copy-key for an action's warm confirmation (the route returns it)."""
    if action not in RESULT_KEY_BY_ACTION:
        raise KeyError(f"no result copy key for action {action!r}")
    return RESULT_KEY_BY_ACTION[action]


def all_emitted_strings() -> List[str]:
    """Every governed string the Hub can emit (the guard test iterates this).

    Renders every copy-key with BOTH a representative name and the neutral fallback, so the
    guard checks the substituted form a Coordinator / helper actually reads (a name could
    never be a prohibited word, but the rendered sentence is what ships). Keeping the
    enumeration next to the copy means a new key is covered by the test automatically.
    """
    strings: List[str] = []
    for key in COPY:
        strings.append(render(key, name="Sam"))
        strings.append(render(key, name=""))  # the neutral-fallback form
    return strings
