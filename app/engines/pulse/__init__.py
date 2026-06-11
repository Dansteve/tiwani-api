"""Pulse: post-activity check-in. STUB, NO LOGIC YET.

Spec: Product.md section 4.7. Module file: HardRules/Api/Modules/Pulse.md.
Data objects: HardRules/Api/Modules/Models.md (pulse_record).

What it will be: a two-tap outcome capture (outcome Well/Okay/Difficult, then the
main challenge dimension; both required), meant to take under 10 seconds.

Scheduling is set by the LCE (section 4.4 step 9): activity date + 2 hours, or
09:00 the next day if no date. The api owns the schedule and trigger.

On completion the api, in this order (do not move into the app):
  1. writes the pulse_record (outcome_code, challenge_dimension, the stored
     tier_recommended and chapter, timestamp)
  2. recalculates the chapter LCI (Index.md) using outcome x the STORED recommended
     tier (never re-derived), within 10 seconds
  3. evaluates Erosion Alerts for that chapter (Alerts.md)
  4. updates the Strategy Library outcome counts (Strategies.md)

A Pulse persists across dashboard opens until completed or dismissed twice; after
the second dismiss it is recorded as skipped, a 0 adjustment to the LCI (never a
penalty).

BLOCKED behind the LCE/LCI/Alerts it triggers (SeedData.md Q7).
"""
