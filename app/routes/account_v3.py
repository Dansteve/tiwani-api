"""v3 self-service account routes: data export, account closure, reactivation.

Thin HTTP only (HardRules/Api/SETUP.md): parse, call the account service, serialize. These
are the data-rights actions a Coordinator can take on their OWN account:

  GET  /api/v3/me/export          download a JSON document of the caller's own data.
  POST /api/v3/me/delete          close the caller's account (SOFT delete; data retained 90 days).
  GET  /api/v3/me/account-status  the caller's closure state + the 90-day recovery window.
  POST /api/v3/me/reactivate      reopen a soft-deleted account within the 90-day window.

All depend on get_current_user_allow_deleted, NOT get_current_user: they must work for a user
acting on their own account while it is closed. Export reads the caller's data up to the
instant they close; delete is idempotent (an already-closed account can re-issue the
soft-delete without the 410 closure block pre-empting it); and account-status / reactivate are
specifically how a SOFT-DELETED caller checks and lifts their own closure (the 410 block would
otherwise lock them out). Every read and write is RLS-scoped through the service, so no route
can ever touch another user's data.

Account deletion is a SOFT delete with a single 90-day recovery window (Docs/FeatureList.md,
Product.md section 4.11): it sets user_profile.deleted_at and the data is RETAINED (not
scrubbed) for 90 days, during which signing back in (POST /me/reactivate) reopens the account.
At 90 days the data is permanently deleted by a manual/operational purge (no automated job).
While an account is closed, the soft-delete access block in get_current_user rejects every
OTHER v3 route with 410, so the closed account can neither read nor write until it reactivates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import AuthedUser, get_current_user_allow_deleted
from app.services import account as account_service

router = APIRouter()


class AccountDeletionResult(BaseModel):
    """The POST /api/v3/me/delete confirmation.

    deleted is always True on success; deleted_at is the server timestamp the account was
    closed at (set/refreshed by this call). The app shows a calm confirmation and signs the
    user out; it does not need any other field.
    """

    deleted: bool
    deleted_at: datetime


class AccountStatus(BaseModel):
    """The GET /api/v3/me/account-status payload (the post-login closure check).

    deleted is True when the account is soft-deleted. deleted_at is when it was closed (null
    if active). hard_delete_due_at is the COMPUTED moment the data becomes due for the manual
    purge (deleted_at + 90 days; null if active). reactivatable is True only while the account
    is deleted AND still inside the 90-day window, so the app shows the reactivation prompt
    exactly when reactivation will succeed.
    """

    deleted: bool
    deleted_at: Optional[datetime]
    hard_delete_due_at: Optional[datetime]
    reactivatable: bool


class ReactivateResult(BaseModel):
    """The POST /api/v3/me/reactivate confirmation. reactivated is always True on success.

    Success means the account is live again (or was never closed); the app then proceeds into
    the app. A reactivation past the 90-day window is a 410, not this body.
    """

    reactivated: bool


@router.get("/me/export")
def export_my_data(
    user: AuthedUser = Depends(get_current_user_allow_deleted),
) -> JSONResponse:
    """Return the caller's own data as a downloadable JSON document (RLS-scoped).

    The service gathers, under the caller's token, every row that belongs to them
    (user_profile, child_profile, activity_record, pulse_record, lci_snapshot, alert_record,
    card_record); RLS plus the per-table user_id filter mean it can only ever contain the
    caller's data. The response carries a Content-Disposition attachment header so a browser
    downloads it as a file rather than rendering it inline. jsonable_encoder turns the raw
    rows (datetimes, etc.) into JSON-native values.
    """
    document = account_service.export_account(user)
    payload = jsonable_encoder(document)
    filename = "tiwani-account-export.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/me/delete", response_model=AccountDeletionResult)
def delete_my_account(
    user: AuthedUser = Depends(get_current_user_allow_deleted),
) -> AccountDeletionResult:
    """Close the caller's account (SOFT delete) and confirm.

    Sets user_profile.deleted_at = now() on the caller's own row (RLS-scoped) and revokes the
    caller's active share links, retaining the data per the retention policy: closed and
    RECOVERABLE for 90 days (sign back in to reactivate), then permanently deleted by a manual
    operational purge (no automated job). It does NOT erase the data on the spot. Idempotent:
    a repeat call on an already-closed account refreshes the timestamp and still returns a 200
    confirmation (this route does not apply the closure block, so a second delete is not
    pre-empted). After this returns, the app signs the user out; every other v3 route then
    rejects the closed account with 410 until it reactivates within the window.
    """
    result = account_service.soft_delete_account(user)
    return AccountDeletionResult.model_validate(result)


@router.get("/me/account-status", response_model=AccountStatus)
def my_account_status(
    user: AuthedUser = Depends(get_current_user_allow_deleted),
) -> AccountStatus:
    """Report the caller's closure state + the computed 90-day recovery window.

    Depends on get_current_user_allow_deleted so a SOFT-DELETED caller can reach it (the 410
    block would otherwise lock them out): this is exactly how the app learns, after login, that
    the account is closed so it can offer reactivation. Reads the caller's own
    user_profile.deleted_at (RLS-scoped) and returns { deleted, deleted_at, hard_delete_due_at,
    reactivatable }, where hard_delete_due_at is computed (deleted_at + 90 days) and
    reactivatable is true only inside the window. An active account returns deleted false with
    both timestamps null.
    """
    return AccountStatus.model_validate(account_service.account_status(user))


@router.post("/me/reactivate", response_model=ReactivateResult)
def reactivate_my_account(
    user: AuthedUser = Depends(get_current_user_allow_deleted),
) -> ReactivateResult:
    """Reactivate the caller's soft-deleted account within the 90-day recovery window.

    Depends on get_current_user_allow_deleted so a SOFT-DELETED caller can reach it. Within the
    window, clears user_profile.deleted_at on the caller's own row (RLS-scoped) and the account
    is live again. Past the 90-day window the data is due for / past the manual hard delete, so
    reactivation is refused with 410 Gone (AccountPurgedError). A call on an account that is not
    deleted is an idempotent 200 success (the app only offers this when status says deleted, so
    an already-active reactivate is a benign race). The app proceeds into the app on success and
    re-reads account-status. Cards revoked at deletion stay revoked (the user re-shares).
    """
    try:
        result = account_service.reactivate_account(user)
    except account_service.AccountPurgedError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This account is past its recovery window and can no longer be reactivated",
        ) from exc
    return ReactivateResult.model_validate(result)
