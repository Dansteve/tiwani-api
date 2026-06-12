"""Active care-recipient plumbing model (v3): the role-tagged recipient list behind the
app's recipient switcher (Docs/FeatureDecisions.md, the 2026-06-12 "Helper Village ACCESS"
entry, refinement 1).

GET /api/v3/recipients returns the UNION of (a) the recipients the caller OWNS and (b) the
recipients shared WITH the caller (their active non-owner recipient_membership rows), each
tagged with the caller's ROLE. This is the list the app's RecipientProvider reads to resolve
the active recipient AND to drive the shell's visibility ceiling (an owner reaches every
screen; a viewer reaches only the Village needs + the shared Continuity Card).

THE CEILING (refinement 1, security-critical): surfacing a member recipient here must NOT
widen what a viewer can READ. For an OWNED recipient the first name comes from the owned
child_profile; for a SHARED recipient it comes ONLY from the capped member-card path
(get_recipient_card_for_member, the same path shared_with_me uses), never child_profile
(which RLS blocks for a member). So a member entry carries the recipient id + the FIRST NAME
ONLY + the caller's role, and nothing of the raw profile / LCI / alerts / pulse.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class RecipientRole(str, Enum):
    """The caller's role on a care recipient surfaced in the switcher.

    owner : the caller CREATED the recipient (child_profile.user_id == them); full access.
    viewer: the recipient was SHARED with the caller read-only (the Shared-Child MVP role);
            the visibility CEILING holds (the Village needs + the shared Card only).
    editor: a reserved co-coordinator role (not surfaced by the MVP UI); treated as non-owner
            by the shell, so it stays at the viewer ceiling until the editor surface ships.

    Distinct from models.sharing.ShareRole (the INVITABLE subset, viewer/editor only): this
    enum adds `owner` because the switcher list includes the caller's OWN recipients.
    """

    OWNER = "owner"
    VIEWER = "viewer"
    EDITOR = "editor"


class ActiveRecipient(BaseModel):
    """One care recipient the caller can act on, role-tagged, for the app switcher.

    The minimal, ceiling-safe shape: the recipient id, the FIRST name only, and the caller's
    role. Deliberately NOT the full child_profile (name / age_band / support_level_code /
    tags): a member must never receive the raw profile, so the switcher plumbing carries only
    what it needs (a label + an id + a role). Owner-only screens that need the full profile
    read it through the owner-scoped GET /child / GET /children (RLS-allowed for the owner).
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str
    first_name: str
    role: RecipientRole
