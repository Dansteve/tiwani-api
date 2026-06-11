"""Pulse: the post-activity check-in (Product.md section 4.7).

The two-tap outcome capture (outcome Well / Okay / Difficult, then the main
challenge dimension) that feeds the LCI and (Task 7) the alerts. Module file:
HardRules/Api/Modules/Pulse.md. Data object: Models.md (pulse_record, migration
0004).

Where the code lives (the Task 5 split between pure engines and the data/clock
layer is kept): the Pulse has no pure SCORING of its own (the index math is the LCI
engine, app/engines/lci), so its recording + orchestration is the data layer in
app/services/pulse.py, which:
  1. reads the caller's activity_record (the STORED chapter + recommended tier; the
     tier is never re-derived here, the Pulse hard rule),
  2. enforces one pulse per activity (a duplicate is a 409),
  3. writes the pulse_record (outcome, challenge dimension, stored tier + chapter),
  4. recomputes the chapter LCI and snapshots it (section 4.8, within 10 seconds),
  5. exposes the pending Pulses (scheduled time passed, no pulse yet).

The Erosion Alert evaluation (section 4.7 step 3) and the Strategy Library outcome
counts (step 4) are Tasks 7 and 9; they hook in after the LCI is recomputed (the
seam is marked in app/services/pulse.py).

This package re-exports the service's typed errors so a route can import the Pulse
contract from one place; the recording entry points are record_pulse and
list_pending_pulses in app/services/pulse.py.
"""

from app.services.pulse import ActivityNotFoundError, AlreadyPulsedError

__all__ = ["ActivityNotFoundError", "AlreadyPulsedError"]
