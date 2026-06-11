"""Strategy Library: strategies that get better with use. STUB, NO LOGIC YET.

Spec: Product.md section 4.10. Module file: HardRules/Api/Modules/Strategies.md.
Data objects: HardRules/Api/Modules/Models.md (strategy_library_item).
Its ranking output is consumed by the LCE (Engine.md step 7).

What it will be: every strategy that appears in a completed plan is saved
automatically and tagged to its chapter and scenario; over time strategies are
promoted, suppressed, or surfaced across chapters.

The exact rules to build (Product.md section 4.10, Strategies.md):
  - promotion (appears first next time): positive outcomes >= 2 AND more
    positives than negatives, specific to that recipient and scenario
  - suppression (excluded next time): removed 3 times for the same strategy +
    scenario; scenario-specific and reversible
  - outcome attribution (MVP): a Pulse outcome applies EQUALLY to every strategy
    in that plan (a deliberate MVP simplification, Q8; do not "fix" without the
    PRODUCT OWNER)
  - cross-context surfacing: a strategy with positive outcomes >= 2 is offered in
    other chapters when it matches a high-scoring dimension, labelled "Also
    worked in [chapter]", dismissible per chapter

BLOCKED behind the LCE that consumes its ranking and the Pulse that updates its
counts (SeedData.md Q7).
"""
