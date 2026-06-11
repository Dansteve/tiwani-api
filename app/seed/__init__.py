"""Seed: the LCE Knowledge Base + Tag Architecture, loaded into the engine lookups.

Module file: HardRules/Api/Modules/SeedData.md. The engine reads seeded rows,
never hardcoded scores (HardRules/Api/SETUP.md, Engine.md).

STATUS: a TIWANI-derived v1 is authored. The two source documents are versioned
Python sources, validated on load and read by the LCE:
  - knowledge_base_v1.py: the scenario matrix (per (chapter, activity) base
    {temporal, sensory, logistical, human} scores + ranked strategy text), the
    input to LCE step 1 and step 7;
  - tag_architecture_v1.py: the per-tag dimension modifiers (+1/+2), the input to
    LCE step 3, with the +2-per-dimension cap applied at engine apply time;
  - loader.py: load_seed() assembles + HARD-FAIL validates both and returns the
    SeedTables the engine reads (get_base_scores, chapter_average, get_strategies,
    tag_contribution).

PROVENANCE (read this). The numbers are a TIWANI-derived v1 authored from the
shared four-dimension rubric (SeedData.md), because the original companion
documents ("LCE Complete Knowledge Base v1.0", "Tag Architecture v1.0") were never
in the repo and the owner does not have them (Q7). The owner explicitly authorised
building a transparent, ratifiable v1 from first principles: every value carries a
written rationale, the whole set is labelled "TIWANI-derived v1, pending owner
ratification + clinical sign-off" (Tasks 7/12), and it is stored as DATA the engine
reads, so any cell is owner-changeable without a code edit. A score or modifier
change is a new seed version (SeedData.md), owned by the PRODUCT OWNER.
"""

from app.seed.loader import (
    MIN_SCENARIOS_PER_CHAPTER,
    SeedTables,
    SeedValidationError,
    load_seed,
    write_seed_to_db,
)

__all__ = [
    "load_seed",
    "write_seed_to_db",
    "SeedTables",
    "SeedValidationError",
    "MIN_SCENARIOS_PER_CHAPTER",
]
