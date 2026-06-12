"""v1 Pulse routes (the post-activity check-in).

Thin HTTP only (HardRules/Api/SETUP.md): parse and validate, call the pulse service
(which records the pulse and triggers the LCI recompute), serialize. Every route
requires the current-user dependency (401 without a valid bearer token); the writes
are user-scoped through the service with Supabase RLS as the backstop.

Registered under /api/v1 in main.py. The app posts the outcome here; the api records
it, recomputes the chapter LCI (section 4.8), and (Tasks 7/9) evaluates alerts and
updates strategy counts.

Endpoints:
  POST /api/v1/pulses          record a Pulse for an activity {activity_id,
                               outcome_code, challenge_dimension?}; returns the
                               stored PulseRecord. 404 if the activity is not the
                               caller's; 409 if a Pulse already exists for it.
  GET  /api/v1/pulses/pending  the activities whose scheduled Pulse time has passed
                               with no pulse yet (the in-app prompt source).
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthedUser, get_current_user
from app.models.pulse import PendingPulse, PulseRecord, PulseSubmission
from app.services import pulse as pulse_service

router = APIRouter()


@router.post("/pulses", response_model=PulseRecord)
def create_pulse(
    payload: PulseSubmission,
    user: AuthedUser = Depends(get_current_user),
) -> PulseRecord:
    """Record a Pulse for an activity, recompute the chapter LCI, return the record.

    The outcome (well / okay / difficult, or skipped after a dismiss-twice) is stored
    against the activity with its STORED chapter and recommended tier; the chapter LCI
    is recomputed and snapshotted within 10 seconds. 404 if the activity is unknown or
    not the caller's; 409 if a Pulse already exists for it (one pulse per activity,
    section 4.7).
    """
    try:
        return pulse_service.record_pulse(
            user,
            activity_id=payload.activity_id,
            outcome_code=payload.outcome_code,
            challenge_dimension=payload.challenge_dimension,
        )
    except pulse_service.ActivityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Activity not found",
        ) from exc
    except pulse_service.AlreadyPulsedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pulse has already been recorded for this activity",
        ) from exc


@router.get("/pulses/pending", response_model=List[PendingPulse])
def list_pending(
    user: AuthedUser = Depends(get_current_user),
) -> List[PendingPulse]:
    """The caller's pending Pulses: scheduled time passed, no pulse recorded yet.

    The source for the in-app check-in prompt (section 4.7). The app decides how to
    present and when to mark one skipped (dismiss twice); the api reports what is
    still pending.
    """
    return pulse_service.list_pending_pulses(user)
