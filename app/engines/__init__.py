"""Engines: all domain logic, deterministic and pure where possible.

Per HardRules/Api/SETUP.md, every piece of TIWANI domain logic lives here, never
in a route (routes stay thin: parse, call an engine, serialize). The subpackages:

  - lce        the Life Continuity Engine        (Product.md section 4.4, AUTHORITATIVE)
  - lci        the Life Continuity Index         (Product.md section 4.8, AUTHORITATIVE)
  - alerts     Erosion Alerts                    (Product.md section 4.9, AUTHORITATIVE)
  - pulse      Pulse scheduling and recording    (Product.md section 4.7)
  - cards      the Continuity Card               (Product.md section 4.6)
  - strategies the Strategy Library              (Product.md section 4.10)

STATUS: STUBS ONLY. Each subpackage currently holds a docstring that points to
its authoritative spec section and its module file, and NO logic. They are not
implemented in this foundation slice.

The three AUTHORITATIVE engines (lce, lci, alerts) must be built to the number
and the word in Product.md, with table-driven tests pinning every boundary
(HardRules/Api/SETUP.md, Docs/Decisions.md D4). The LCE is deterministic and
server-side: same inputs always produce the same scores, tier, and ranked
strategies (no AI, no randomness, no clock inside scoring).

BLOCKER (HardRules/Api/Modules/SeedData.md, Q7): the LCE cannot run without the
scenario matrix (per-activity base scores) and the Tag Architecture (per-tag
modifier values), which live in two companion documents NOT in this repo ("TIWANI
LCE Complete Knowledge Base v1.0", "TIWANI Child Profile Tag Architecture v1.0").
Do not fabricate base scores or modifier values. Implementing lce (and the
downstream lci/alerts/pulse/strategies that consume its output) is BLOCKED on the
PRODUCT OWNER supplying those documents.
"""
