"""LCE: the Life Continuity Engine (Product.md section 4.4, AUTHORITATIVE).

A deterministic, rules-based (not AI) engine. Input: a care recipient profile (the
support level + permanent tags), a chosen activity and its chapter, and any "today"
flags. Output: four pressure-dimension scores (temporal, sensory, logistical,
human; each 1 to 5), a total (4 to 20), a participation tier, ranked strategies,
and a one-line non-clinical explanation per dimension. Same inputs always produce
the same output: no AI, no randomness, no clock inside the scoring.

Module file: HardRules/Api/Modules/Engine.md. Seed inputs: SeedData.md. Data
object: Models.md (activity_record). The engine reads seeded rows through
app.seed.SeedTables and never hardcodes a score.

Layout:
  scoring.py       the calc seam: round-after-multiplier + cap-at-5 (the Task 12
                   score-resolution decision lives behind these two functions).
  strategies.py    section 4.4 step 7 ranking + the Task 9 promotion/suppression/
                   cross-context hook.
  explanations.py  section 4.4 step 10 per-dimension non-clinical sentences.
  engine.py        run_engine: the section 4.4 steps 1 to 7 + 10, pure.

Steps 8 (store the activity_record + confirm the write) and 9 (schedule the Pulse)
are the persistence/clock steps and live in app/services/plans.py, which calls
run_engine. Step 11 (recompute the LCI + evaluate alerts on Pulse completion) is
Tasks 6/7.
"""

from app.engines.lce.engine import EngineResult, run_engine
from app.engines.lce.strategies import RankedStrategy

__all__ = ["run_engine", "EngineResult", "RankedStrategy"]
