"""GOVERNED user-facing copy for Shared-Child sharing (Docs/FeatureDecisions.md,
the Shared-Child REFINE entry, refinement 7).

The warm, capacity-framed strings a Coordinator and the person they share with read:
the invite line, the linked-state line, the per-recipient consent text that is RECORDED
(refinement 5), and the roster labels. The copy carries the EXTRA bar the sharing
surface sets (refinement 7): non-clinical, non-surveillance, and it NEVER exposes the
internal RBAC role names ("viewer" / "owner") as a user-facing label. It speaks in
capacity terms ("people who can see [name]'s card", "you can change this any time"),
never case-management or watching terms.

Every string here is run through the sharing guard (app/engines/sharing/guard.py
assert_clean) at build time, so a prohibited word can never leave this module. The
copy-KEY constants are the cross-layer contract: the api returns a `copy_key` alongside
each governed surface so the app can render the matching localized string, and the
recorded consent stores the BUILT text verbatim (so the record is self-describing).

What this models is COPY only: no scoping, no persistence, no role logic. The service
(app/services/sharing.py) decides who may do what; this module only shapes the words.
"""

from __future__ import annotations

from typing import Dict

from app.engines.sharing.guard import assert_clean

# ---------------------------------------------------------------------------
# Copy keys: the stable identifiers the api returns so the app can render the
# matching string (and so a recorded consent names which text version was shown).
# These are NOT user-facing; they are the contract between the api and the app.
# ---------------------------------------------------------------------------

CONSENT_COPY_KEY_CHILD = "sharing.consent.child"
CONSENT_COPY_KEY_ADULT = "sharing.consent.adult"
INVITE_COPY_KEY = "sharing.invite.intro"
LINKED_COPY_KEY = "sharing.linked.intro"
ROSTER_EMPTY_COPY_KEY = "sharing.roster.empty"
ROSTER_TITLE_COPY_KEY = "sharing.roster.title"
REVOKED_COPY_KEY = "sharing.revoked.confirm"
ADULT_BLOCKED_COPY_KEY = "sharing.adult_blocked"

# A neutral, non-identifying fallback when a recipient name is missing, so the copy
# always reads. Mirrors the card builder's first_name_only fallback in spirit (warm,
# never a blank).
_NEUTRAL_NAME = "the person you support"

# ---------------------------------------------------------------------------
# The governed strings. {name} is the recipient's FIRST name (the only identifier the
# sharing copy uses, the same privacy bar as the card). No clinical word, no
# surveillance word, no role-name label.
# ---------------------------------------------------------------------------

# The consent text RECORDED for a CHILD recipient (refinement 5): the creating
# Coordinator confirms they have the authority to share. Stored verbatim in
# share_consent.consent_text. Capacity-framed, plain, no clinical/surveillance words.
_CONSENT_CHILD = (
    "I confirm I have the authority to share {name}'s support information with the "
    "person I am inviting, and that I can change or stop this at any time."
)

# The consent text RECORDED for an ADULT recipient (D8): the adult records their own
# consent before any share. Same shape, first-person from the adult.
_CONSENT_ADULT = (
    "I agree to share my support information with the person being invited, and I "
    "understand I can see who can access it and change or stop this at any time."
)

# The invite line the Coordinator sees when they set up a share (and the basis of the
# message the invited person receives). Warm, sets the helper posture, names what is
# shared (the card) and what is NOT (nothing else). No "viewer", no "case".
_INVITE_INTRO = (
    "You are inviting someone to see {name}'s support card, the same one-page summary "
    "you would hand a helper. They will only ever see that card, nothing else, and you "
    "can change or stop their access whenever you like."
)

# The linked-state line the invited person sees once they have joined: what they can
# see, framed as help, not access-control. No role label.
_LINKED_INTRO = (
    "You can see {name}'s support card here. It is a short summary to help you support "
    "{name} well. The family keeps it up to date and can change what you see at any time."
)

# The title of the "who can see [name]'s information" roster (refinement 6). The
# capacity framing the board requires, never "viewers" / "the owner".
_ROSTER_TITLE = "People who can see {name}'s support card"

# The empty-roster line (no one has been invited yet).
_ROSTER_EMPTY = "No one else can see {name}'s support card yet."

# The confirmation after an instant revoke (refinement 6): plain, reassuring, no blame.
_REVOKED_CONFIRM = (
    "Done. They can no longer see {name}'s support card. You can invite them again any "
    "time."
)

# The calm, capacity-framed line when an adult-recipient share is blocked for the MVP
# because the adult has not yet recorded their own consent (refinement 5, the adult
# block; mirrors the one-recipient 409 tone). No guilt, no urgency.
_ADULT_BLOCKED = (
    "Before you can share {name}'s support card, {name} needs to agree to it themselves. "
    "Ask them to confirm, and you will be able to invite people straight after."
)


def _first_name(name: str) -> str:
    """The recipient's first name for the copy, or a neutral fallback.

    The sharing copy uses the FIRST name only (the card's privacy bar). An empty or
    whitespace-only name falls back to a neutral, non-identifying phrase so the copy
    still reads warmly.
    """
    token = (name or "").strip().split()
    return token[0] if token else _NEUTRAL_NAME


def consent_text(recipient_name: str, *, subject_kind: str) -> str:
    """The governed consent text to record for a share (refinement 5).

    subject_kind selects the child (the Coordinator consents as the responsible adult)
    or adult (the recipient consents to their own share) wording. The returned string is
    what record_share_consent / share_recipient_invite stores verbatim in
    share_consent.consent_text, so the recorded consent is self-describing. Guarded
    before it is returned.
    """
    name = _first_name(recipient_name)
    template = _CONSENT_ADULT if subject_kind == "adult" else _CONSENT_CHILD
    text = template.format(name=name)
    assert_clean(text)
    return text


def consent_copy_key(subject_kind: str) -> str:
    """The copy key for the consent text version (so the app can render/localize it)."""
    return CONSENT_COPY_KEY_ADULT if subject_kind == "adult" else CONSENT_COPY_KEY_CHILD


def invite_intro(recipient_name: str) -> str:
    """The governed invite line shown to the Coordinator (and basis of the message)."""
    text = _INVITE_INTRO.format(name=_first_name(recipient_name))
    assert_clean(text)
    return text


def linked_intro(recipient_name: str) -> str:
    """The governed linked-state line shown to the person who has joined."""
    text = _LINKED_INTRO.format(name=_first_name(recipient_name))
    assert_clean(text)
    return text


def roster_title(recipient_name: str) -> str:
    """The governed title of the 'who can see [name]'s card' roster (refinement 6)."""
    text = _ROSTER_TITLE.format(name=_first_name(recipient_name))
    assert_clean(text)
    return text


def roster_empty(recipient_name: str) -> str:
    """The governed empty-roster line (no one invited yet)."""
    text = _ROSTER_EMPTY.format(name=_first_name(recipient_name))
    assert_clean(text)
    return text


def revoked_confirm(recipient_name: str) -> str:
    """The governed confirmation line after an instant revoke (refinement 6)."""
    text = _REVOKED_CONFIRM.format(name=_first_name(recipient_name))
    assert_clean(text)
    return text


def adult_blocked(recipient_name: str) -> str:
    """The governed calm line when an adult-recipient share is blocked (refinement 5)."""
    text = _ADULT_BLOCKED.format(name=_first_name(recipient_name))
    assert_clean(text)
    return text


def all_emitted_strings() -> list[str]:
    """Every governed string this module can emit, for the permanent guard test.

    Renders each governed surface with a representative recipient name and with the
    neutral fallback, so the guard test proves the WHOLE sharing copy surface (both the
    named and the fallback forms) is clean. A future copy edit that introduced a
    prohibited word would make the guard test fail here.
    """
    out: list[str] = []
    for name in ("Ade", ""):  # a real first name and the empty (neutral-fallback) case
        out.append(consent_text(name, subject_kind="child"))
        out.append(consent_text(name, subject_kind="adult"))
        out.append(invite_intro(name))
        out.append(linked_intro(name))
        out.append(roster_title(name))
        out.append(roster_empty(name))
        out.append(revoked_confirm(name))
        out.append(adult_blocked(name))
    return out


# The copy-key -> human-description map, exposed so the api contract and the app stay in
# sync on which keys exist. Description only; the rendered string comes from the
# functions above (which are guarded).
COPY_KEYS: Dict[str, str] = {
    CONSENT_COPY_KEY_CHILD: "Consent text recorded when sharing a child recipient.",
    CONSENT_COPY_KEY_ADULT: "Consent text an adult recipient records for their own share.",
    INVITE_COPY_KEY: "Intro shown to the Coordinator setting up a share.",
    LINKED_COPY_KEY: "Intro shown to the person who has joined and can see the card.",
    ROSTER_TITLE_COPY_KEY: "Title of the 'who can see [name]'s card' list.",
    ROSTER_EMPTY_COPY_KEY: "Shown when no one else can see the card yet.",
    REVOKED_COPY_KEY: "Confirmation after access is removed.",
    ADULT_BLOCKED_COPY_KEY: "Calm line when an adult recipient has not yet consented.",
}
