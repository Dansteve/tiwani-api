"""Continuity Card engine: assemble a one-page shareable support summary.

Spec: Product.md section 4.6. Module file: HardRules/Api/Modules/Cards.md.
Data objects: HardRules/Api/Modules/Models.md (continuity_card / card_record).

What it is: a one-page support summary a Coordinator generates for a HELPER (a
babysitter, teacher, or respite carer) and shares via a link that needs NO account.
It restates one activity's plan, the participation tier, and the top strategies in
plain, warm, NON-CLINICAL words so a helper who has never met the care recipient can
support them well.

This package is the PURE assembler (app/engines/cards/builder.py): given a stored
activity_record + the care recipient's name it shapes the SAFE CardContent, using the
FIRST name only, and runs every helper-facing string through the SHARED non-clinical
guard (app/engines/alerts/guard.py: one prohibited-words definition, reused, not a
second guard). The data layer (verify ownership, generate the token, store the
card_record, read by token) is app/services/cards.py; the routes are
app/routes/cards.py; the table + the careful token read path are migration
0007_card_record.sql.

SAFETY (HardRules/Api/Modules/Cards.md): the share link carries ZERO PII beyond the
first name (an opaque token + the safe content); contact details are out of scope for
this surface; the link expires after 30 days, enforced server-side. The card copy is
screened by a clinical reviewer and must stay non-clinical and non-coercive.
"""

from app.engines.cards.builder import (
    MAX_CARD_STRATEGIES,
    build_card_content,
    first_name_only,
)

__all__ = [
    "build_card_content",
    "first_name_only",
    "MAX_CARD_STRATEGIES",
]
