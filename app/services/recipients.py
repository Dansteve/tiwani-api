"""Active care-recipient service (v3): the role-tagged recipient list behind the switcher.

The thin composition layer for GET /api/v1/recipients (Docs/FeatureDecisions.md, the
2026-06-12 "Helper Village ACCESS" entry, refinement 1, the load-bearing security-critical
fix). It returns the UNION of:
  (a) the recipients the caller OWNS (profile.list_children, role=owner), and
  (b) the recipients shared WITH the caller (sharing.shared_with_me, role=viewer/editor),

so a helper who redeemed an invite (a recipient_membership with no owned child_profile) finally
reaches the active-recipient plumbing and can open the Village to claim a need. Before this,
GET /api/v1/children returned only OWNED recipients (.eq("user_id", user.id)), so a member-only
helper had an empty switcher, a null active recipient, and a dead-ended Village ("Add the
person you care for first") -- the live P0 defect.

THE CEILING (security-critical): this MUST NOT widen what a viewer can read. It reuses the
EXISTING, RLS-reviewed paths only:
  - owned recipients come from list_children (owner-scoped child_profile under RLS),
  - shared recipients come from shared_with_me, whose first name is read ONLY through the
    capped get_recipient_card_for_member RPC (never child_profile, which RLS blocks for a
    member).
So a member entry exposes the recipient id + the FIRST NAME ONLY + the caller's role, and
nothing of the raw profile / LCI / alerts / pulse. The real boundary is the owner-only RLS on
those tables (proven in tests/test_shared_child_rls.py); this service queries none of them for
a member.
"""

from __future__ import annotations

from typing import List, Optional, Set

from app.auth import AuthedUser
from app.models.recipient import ActiveRecipient, RecipientRole
from app.services import profile as profile_service
from app.services import sharing as sharing_service


def _first_name(name: Optional[str]) -> str:
    """The recipient's first name only (the switcher's warm, ceiling-safe label)."""
    token = (name or "").strip().split()
    return token[0] if token else ""


def list_active_recipients(user: AuthedUser) -> List[ActiveRecipient]:
    """The caller's recipients for the switcher: OWNED (role=owner) + SHARED (viewer/editor).

    Owned first (newest-first, the list_children order), then the recipients shared with the
    caller. De-duped by id (an owner is never a non-owner member of their own recipient, but a
    defensive guard keeps a single row per recipient regardless). Empty for a brand-new user
    with no recipients and no shares (a valid switcher state -> a 200 empty list).

    BOUNDED (the every-list-is-capped rule): a Coordinator manages a small set of recipients,
    so the switcher list needs no cursor; both underlying reads (list_children and
    shared_with_me) carry their own MAX_BOUNDED_ROWS cap, so this composed list is bounded
    transitively without truncating any real recipient.
    """
    recipients: List[ActiveRecipient] = []
    seen: Set[str] = set()

    # (a) OWNED recipients (role=owner): the owner-scoped rows, first-named for the switcher.
    for row in profile_service.list_children(user):
        rid = row.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        recipients.append(
            ActiveRecipient(
                id=rid,
                first_name=_first_name(row.get("name")),
                role=RecipientRole.OWNER,
            )
        )

    # (b) SHARED recipients (role=viewer/editor): reuse the capped shared_with_me path, whose
    # first name comes ONLY from get_recipient_card_for_member (the ceiling), not child_profile.
    shared = sharing_service.shared_with_me(user)
    for entry in shared.recipients:
        if entry.recipient_id in seen:
            continue
        seen.add(entry.recipient_id)
        recipients.append(
            ActiveRecipient(
                id=entry.recipient_id,
                first_name=entry.recipient_first_name,
                role=RecipientRole(entry.role),
            )
        )

    return recipients
