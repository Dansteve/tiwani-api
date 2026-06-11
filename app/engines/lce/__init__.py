"""LCE: the Life Continuity Engine. STUB, NO LOGIC YET.

Authoritative spec: Product.md section 4.4 (AUTHORITATIVE, build to the number).
Module file: HardRules/Api/Modules/Engine.md. Seed inputs: HardRules/Api/Modules/SeedData.md.
Data objects: HardRules/Api/Modules/Models.md (activity_record).

What it will be: a deterministic, rules-based (not AI) function. Input: a care
recipient profile, a chosen activity, its chapter, and any "today" flags. Output:
four pressure-dimension scores (temporal, sensory, logistical, human; each 1 to 5),
a total (4 to 20), a participation tier, and ranked strategies. Same inputs always
produce the same output: no AI, no randomness, no clock inside the scoring.

The exact sequence to build (Product.md section 4.4, Engine.md):
  1. base scores from the scenario matrix (seeded rows; custom activity falls back
     to the chapter average and the plan says so); round to whole numbers
  2. support multiplier (SL-LOW x1.0, SL-MED x1.2, SL-HIGH x1.4); round; cap each at 5
  3. permanent tag modifiers (additive; tag contribution per dimension capped at +2);
     cap each at 5
  4. "today" flag modifiers (additive); cap each at 5
  5. total = temporal + sensory + logistical + human (4 to 20)
  6. tier: 4 to 8 Full Engagement, 9 to 13 Modified Participation, 14 to 20 Continuity Pivot
  7. rank strategies (Strategies.md): promoted first, dimension >= 3 matches,
     suppressed excluded, cross-context appended
  8. store the activity_record and confirm the write
  9. schedule the Pulse (activity date + 2h, else 09:00 next day)

BLOCKED (SeedData.md Q7): the per-activity base scores and per-tag modifier values
are seed data that lives in two companion documents NOT in this repo. The engine
reads seeded rows, never hardcoded scores. Do not fabricate values. Building this
engine is blocked on the PRODUCT OWNER supplying those documents, then a
table-driven test pinning every Product.md worked number before it is Done.
"""
