"""Erosion Alerts. STUB, NO LOGIC YET.

Authoritative spec: Product.md section 4.9 (AUTHORITATIVE, build to the number
AND the word; the copy is governed). Module file: HardRules/Api/Modules/Alerts.md.
Data objects: HardRules/Api/Modules/Models.md (alert_record).

What it will be: a governed early-warning signal that a chapter has been under
sustained pressure. Triggered by the COMBINATION of recommended tier and Pulse
outcome over time (never one alone), evaluated after every Pulse, per chapter. A
higher level replaces any lower one.

The exact thresholds to build (Product.md section 4.9, Alerts.md):
  - L1 Early signal: Modified/Pivot recommended in >= 3 activities in 30 days
    AND Difficult/Okay in >= 3 Pulses in 30 days
  - L2 Sustained pressure: the L1 thresholds at >= 5 in 30 days, OR chapter LCI
    declining for 3 weekly snapshots in a row
  - L3 Critical erosion: Pivot recommended in >= 3 activities in 14 days AND
    Difficult in >= 3 Pulses in 14 days, OR chapter LCI below 30

The copy (L1/L2/L3 strings + CTAs) is VERBATIM from Product.md section 4.9; the
only substitution is [chapter]. Do not paraphrase.

NON-CLINICAL HARD CONSTRAINT: alerts may only signpost community and statutory
support (Carers UK, IPSEA, SENDIASS, local carer organisations, statutory
rights), never a clinical referral. These words are PROHIBITED in any emitted
alert content: symptoms, diagnosis, condition, mental health, depression,
anxiety disorder, clinical, treatment, therapy. A permanent guard test asserts
none ever appears.

LAUNCH GATE: alerts do not ship to beta without psychiatrist sign-off (tracked in
Tasks/). Implementation consumes the LCE/LCI output, so it is BLOCKED behind them
(SeedData.md Q7), and a table-driven test must pin every threshold plus the
prohibited-words guard before it is Done.
"""
