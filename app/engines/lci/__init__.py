"""LCI: the Life Continuity Index. STUB, NO LOGIC YET.

Authoritative spec: Product.md section 4.8 (AUTHORITATIVE, build to the number).
Module file: HardRules/Api/Modules/Index.md.
Data objects: HardRules/Api/Modules/Models.md (chapter_lci_record, overall_lci_snapshot).

What it will be: a 0 to 100 resilience score, per Life Chapter and overall,
computed server-side from stored Pulse outcomes and the stored recommended tier
(never recomputed in the app, never from free text).

The exact formula to build (Product.md section 4.8, Index.md):
  - start at 50 on a chapter's first Pulse; adjust cumulatively, never reset
  - per-Pulse adjustment by outcome x the activity's recommended tier:
        Well      -> Full +10, Modified +7, Pivot +5
        Okay      -> Full +3,  Modified +5, Pivot +3
        Difficult -> Full -8,  Modified  0, Pivot +2
    (all twelve cells; the Pivot column was recovered 2026-06-11, Decisions.md D4)
  - skipped Pulse: 0 (no effect)
  - bounds 0 to 100, round after each change
  - overall LCI = equal-weighted average of chapters with >= 1 Pulse (no-data
    chapters excluded)
  - trajectory vs 7 days prior: +3 or more Strengthening, within +/-2 Holding
    steady, -3 or more Under pressure, insufficient data Building your picture
  - sparse data (< 3 Pulses in a chapter) shows a "building your picture" label

This is exact and owner-governed (D4): pin all twelve outcome-by-tier cells, the
start-at-50, the bounds and rounding, the overall average, and every trajectory
band in a table-driven test before the LCI ships. It consumes the LCE's stored
output, so it is BLOCKED behind the LCE (SeedData.md Q7).
"""
