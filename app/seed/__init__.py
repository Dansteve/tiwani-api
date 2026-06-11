"""Seed: the LCE Knowledge Base + Tag Architecture, loaded into DB rows.

Module file: HardRules/Api/Modules/SeedData.md. The engine reads seeded rows,
never hardcoded scores (HardRules/Api/SETUP.md, Engine.md).

STATUS: STUB, NO LOADERS YET.

What it will be: loaders that turn two versioned source documents into DB rows:
  - LCE Knowledge Base v1.0: per activity (within a chapter), the base
    {temporal, sensory, logistical, human} scores and the ranked strategy text
    (the scenario matrix the LCE step 1 looks up)
  - Tag Architecture v1.0: per tag code (SN-/TR-/CM-/RC-), the modifier it adds
    and the dimension(s) it affects, with the per-dimension cap (+2) enforced in
    the lookup (what the LCE step 3 applies)

The seed is versioned: a score or modifier change is a new seed version applied
as a migration/seed step, not an ad-hoc DB edit. Seed values are validated on
load (dimensions in range, modifiers within the per-dimension cap, every chapter
present, every referenced tag code defined).

BLOCKED (SeedData.md Q7): the per-activity base scores, the per-tag modifier
values, and the six chapter scenario matrices live in two companion documents
NOT in this repo ("TIWANI LCE Complete Knowledge Base v1.0", "TIWANI Child
Profile Tag Architecture v1.0"). Product.md and the source PRD both state build
should not begin until the engineer has both. Do NOT fabricate base scores or
modifier values. Obtaining these from the PRODUCT OWNER is the first blocker.
"""
