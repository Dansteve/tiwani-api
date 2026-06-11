"""Continuity Card: a one-page shareable support plan. STUB, NO LOGIC YET.

Spec: Product.md section 4.6. Module file: HardRules/Api/Modules/Cards.md.
Data objects: HardRules/Api/Modules/Models.md (continuity_card).

What it will be: a TIWANI-branded one-pager (Deep Teal #04342C, Coral #D85A30
accents) produced SERVER-SIDE as a PDF plus a shareable web link valid for 30
days. Target under 5 seconds to generate.

Contents in order (section 4.6): care recipient's first name only, activity +
date, participation approach, what helps, what to avoid, how they communicate,
the full strategy list written for an outsider, an "if things get difficult"
line, an optional Coordinator contact, and a QR code to tiwanilife.com/?ref=card.

PRIVACY HARD RULES (Cards.md):
  - the share link and the QR code carry ZERO PII: the share URL is an opaque
    token; the QR points only to the marketing site with a ref param
  - contact details appear only if the Coordinator opts in (include_contact on
    the continuity_card; default is no contact)
  - the link expires after 30 days, enforced server-side

Generation depends on a prepared plan (the LCE output), so it is BLOCKED behind
the LCE (SeedData.md Q7).
"""
