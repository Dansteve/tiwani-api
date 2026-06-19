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

# The single runtime substitution for almost every key: the recipient's FIRST name (the
# Card ceiling).
NAME_TOKEN = "{name}"

# The one extra substitution, used ONLY by the covered notice (notification.covered): the
# need's own TITLE (the WHAT the Coordinator typed). It is already INGRESS-guarded at create
# (Fix A) so it carries no health detail, and the whole village already saw it. covered_notice()
# substitutes it and guards the assembled line.
TITLE_TOKEN = "{title}"


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

    # --- card-on-task: the CARD-SHARE consent + the claimer's view (FeatureDecisions 2026-06-17,
    #     flag-gated; psychiatrist + DPO refine-and-approve). The owner confirms this BEFORE the
    #     recipient's Continuity Card is attached to a need; it keys off the CARD-SHARE consent
    #     (DPO L3, distinct from the village-logistics consent above), capacity-framed, no
    #     clinical / surveillance / role words.
    "consent.share_card_on_task": (
        "I confirm I may share {name}'s support card with the one helper who picks up this "
        "task, so they know what helps. The card carries no sensitive details, I can stop "
        "sharing it at any time, and only the helper doing this task can see it."
    ),
    # The calm header above the attached card, shown ONLY to the claimer of the need.
    "need.card_on_task_intro": (
        "{name}'s family shared this support card so you know what helps. Please keep it to "
        "yourself and follow the family's lead."
    ),
    # The 409 backstop if an attach is asked for with no card-share consent on record and no
    # confirmation supplied (the app shows the consent line with the toggle, so this is rare).
    "need.conflict.card_consent_required": (
        "Before sharing the support card, please confirm you are happy to share it."
    ),
    # The 404 line when there is no support card to show for a task (none attached, none live,
    # or the caller is not the live helper for it).
    "need.card.unavailable": "There is no support card to show for this task.",
    # The 422 backstop when an attach is requested while the feature is gated OFF (the app
    # hides the toggle when off, so this only meets a raw API call).
    "need.card_attach_off": "Sharing a support card with a task is not available yet.",

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

    # --- covered / handled: the COORDINATOR-FACING confirmation (the "this is handled, you
    #     can let it go" relief moment, Village "covered" decision). The done_confirmation
    #     above is shown to the HELPER who completed the task; these are shown to the
    #     Coordinator who posted the need, so they LEARN it is covered, not just see a silent
    #     status flip. Framed as RELIEF + gratitude-adjacent (the village handled it), never a
    #     task-tracker tone, never an alarm. -------------------------------------------------
    # The badge word on the owner's board for a need that reached done (a calm "Handled by the
    # village" token, distinct from the in-progress "Someone has offered" claimed badge).
    "need.covered_badge": "Handled by the village",
    # The owner board's warm relief line on a covered (done) need.
    "need.covered_confirmation": (
        "{name}'s village handled this. That is one less thing to hold, you can let it go."
    ),
    # The /notifications page intro (the calm header above the covered notices).
    "notification.covered_intro": (
        "Things {name}'s village has taken off your hands. You can let these go."
    ),
    # One covered notice on /notifications. The {title} is the need's own title (the WHAT the
    # Coordinator typed), which was already guarded at INGRESS (Fix A) so it carries no health
    # detail, and which the whole village already saw, so showing it back to the Coordinator
    # leaks nothing. It is the ONLY need-derived text in the notice (no exact location, no
    # contact, no helper identity: the minimum-visibility rule). The {name} is the recipient's
    # first name (the Card ceiling). Both tokens are substituted by covered_notice() below,
    # which guards the assembled line.
    "notification.covered": (
        "A helper has covered “{title}” for {name}'s village. "
        "You can let this one go."
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

    # --- state-change conflicts (a need moved on before this action). Governed so the raw
    #     Postgres RPC message (the 0017 P0001 RAISE text) never reaches the user; calm,
    #     warm, no role labels. The claim-taken conflict reuses need.claim_taken above. ----
    "need.conflict.consent_required": (
        "Before asking {name}'s village for a hand, take a moment to agree to sharing the "
        "task details with them. You can do that first, then post your ask."
    ),
    "need.conflict.post": (
        "This couldn't be posted just now. Please try again in a moment."
    ),
    "need.conflict.confirm": (
        "This can be confirmed once someone has offered to help with it."
    ),
    "need.conflict.done": (
        "This can be marked as done once someone is covering it."
    ),
    "need.conflict.drop": (
        "There is nothing to step back from here just now."
    ),

    # --- access / not-found (the 403 / 404 paths). Governed so the route's 403/404
    #     details are warm and capacity-framed, never an internal role label (the guard
    #     bars "owner" / "viewer"), consistent with the consent-gate path. "the family"
    #     and "this person's village" stand in for the RBAC roles. ----------------------
    # 403: a member-only action attempted by someone outside the recipient's village
    # (list / detail / claim). "Not part of the village" is the warm, non-role framing.
    "error.not_in_village": (
        "This is for the people in this person's village, and you are not part of it "
        "just now."
    ),
    # 403: an action only the Coordinator who set the need up can take (post / consent /
    # confirm / cancel). Framed as "the family arranges this", never a role label.
    "error.family_only": (
        "Only the family arranging the help can do this."
    ),
    # 403: an action only the helper who offered can take (mark done / step back).
    "error.helper_only": (
        "Only the helper who offered for this can do that."
    ),
    # 404: the need does not exist or is not visible to the caller. Calm, no detail leaked.
    "error.need_not_found": (
        "We could not find this. It may have been completed or taken down."
    ),
    # 422: the Coordinator's typed ask carried wording the Hub will not pass on to helpers
    # (the INGRESS guard, Fix A, the psychiatrist board's input-side requirement). A need is
    # broadcast to a WIDE circle of helpers, so a child's health or clinical detail must not
    # travel in it. Calm, non-clinical, capacity-framed: it nudges a practical re-word, frames
    # the whole village can see it, and NEVER names the word back, NEVER says "clinical" / a
    # diagnosis, and NEVER echoes what was typed (no oracle).
    "need.content.rejected": (
        "Please describe the help you need in everyday words, without health details or "
        "private notes. Your whole village can see this."
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


def covered_notice(*, name: str = "", title: str = "") -> str:
    """The /notifications covered notice (notification.covered), {name} + {title} resolved.

    The Coordinator-facing "a helper has covered '[title]'" line, built from the governed
    template with the recipient's first name AND the need's own title substituted. The title
    was already INGRESS-guarded when the need was posted (Fix A: find_prohibited_words over the
    free-text fields, so no clinical / health detail can be in it), and the whole village
    already saw it; substituting it back into the owner's own notice leaks nothing. The
    assembled line is run through the Hub guard at emit (assert_clean), the backstop. A blank
    title falls back to a neutral phrase so the sentence still reads.
    """
    safe_name = name.strip() or "the family"
    safe_title = title.strip() or "the help you asked for"
    text = (
        COPY["notification.covered"]
        .replace(NAME_TOKEN, safe_name)
        .replace(TITLE_TOKEN, safe_title)
    )
    assert_clean(text)
    return text


def consent_text(*, name: str = "") -> str:
    """The verbatim per-recipient consent text (stored on record_village_consent).

    The exact governed text the Coordinator agrees to and that is persisted verbatim in
    recipient_village_consent.consent_text, so the audit record shows precisely what was
    agreed. {name} resolved; guarded.
    """
    return render("consent.share_with_village", name=name)


def card_consent_text(*, name: str = "") -> str:
    """The verbatim CARD-SHARE consent text the owner confirms when attaching the recipient's
    Continuity Card to a Village task (card-on-task, flag-gated; FeatureDecisions 2026-06-17).

    The card-attach RPC stores this verbatim in share_consent.consent_text when no active
    card-share consent exists yet, so the record shows precisely what the Coordinator agreed
    to. Distinct from consent_text() (the village-logistics consent); the DPO's L3 point is
    that attaching the CARD keys off the CARD-SHARE consent, not the village one. {name}
    resolved; guarded.
    """
    return render("consent.share_card_on_task", name=name)


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
        if key == "notification.covered":
            # The covered notice carries a SECOND token ({title}); render the real substituted
            # form (a representative title + the neutral title) via covered_notice, not render,
            # so the guard checks what a Coordinator actually reads, not a literal "{title}".
            strings.append(covered_notice(name="Sam", title="Pick up from swimming"))
            strings.append(covered_notice(name="", title=""))
            continue
        strings.append(render(key, name="Sam"))
        strings.append(render(key, name=""))  # the neutral-fallback form
    return strings
