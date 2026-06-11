"""Seed: the LCE Knowledge Base + Tag Architecture, loaded into the engine lookups.

Module file: HardRules/Api/Modules/SeedData.md. The engine reads seeded rows,
never hardcoded scores (HardRules/Api/SETUP.md, Engine.md).

STATUS: an EXACT VERBATIM TRANSCRIPTION of the authoritative source documents. The
two source documents are versioned Python sources, validated on load and read by
the LCE:
  - knowledge_base_v1.py: the scenario matrix (per (chapter, activity) base
    {temporal, sensory, logistical, human} scores + tier + ranked strategy text),
    the input to LCE step 1 and step 7;
  - tag_architecture_v1.py: the per-tag dimension modifiers (+1/+2) for the five
    families, the SL multipliers, the input to LCE step 2 and step 3, with the
    +2-per-dimension cap applied at engine apply time;
  - loader.py: load_seed() assembles + HARD-FAIL validates both and returns the
    SeedTables the engine reads (get_base_scores, chapter_average, get_strategies,
    tag_contribution).

PROVENANCE (read this). The numbers are transcribed verbatim from the authoritative
"TIWANI LCE Complete Knowledge Base v1.0" and "Child Profile Tag Architecture v1.0"
(April 2026), which arrived after an earlier TIWANI-derived v1 had been authored from
first principles (when the companion docs were not in the repo). These are the real
product scores, tiers, strategies, and tag modifiers, copied cell for cell. The
transcription CORRECTED the derived v1 where the two differed (notably the Recovery
modifiers, where only RC-SHORT is 0; the all-+1 Sensory family; and the new Triggers
TG- family). The set is owner-ratifiable, swappable data: stored as DATA the engine
reads, so any cell is owner-changeable without a code edit. A value change is a new
seed version (SeedData.md), owned by the PRODUCT OWNER. Clinical sign-off on the
strategy copy still gates launch (Tasks 7/12).
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
