"""v3 self-service account routes: data export + account deletion (closure).

Thin HTTP only (HardRules/Api/SETUP.md): parse, call the account service, serialize. These
are the two data-rights actions a Coordinator can take on their OWN account:

  GET  /api/v3/me/export   download a JSON document of the caller's own data.
  POST /api/v3/me/delete   close the caller's account (SOFT delete; data retained).

Both depend on get_current_user_allow_deleted, NOT get_current_user: they must work for a
user acting on their own account around the moment of closure. Export reads the caller's data
up to the instant they close, and delete is idempotent (an already-closed account can
re-issue the soft-delete without the 410 closure block pre-empting it). Every read and write
is RLS-scoped through the service, so neither route can ever touch another user's data.

Account deletion is a SOFT delete (Docs/FeatureList.md, the retention policy): it sets
user_profile.deleted_at and the data is RETAINED (5 years per policy, then hard-deleted
MANUALLY, no automated job). Once an account is closed, the soft-delete access block in
get_current_user rejects every OTHER v3 route with 410, so the closed account can neither
read nor write.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
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

    Sets user_profile.deleted_at = now() on the caller's own row (RLS-scoped), retaining the
    data per the retention policy (5 years, then a manual hard delete). Idempotent: a repeat
    call on an already-closed account refreshes the timestamp and still returns a 200
    confirmation (this route does not apply the closure block, so a second delete is not
    pre-empted). After this returns, the app signs the user out; every other v3 route then
    rejects the closed account with 410.
    """
    result = account_service.soft_delete_account(user)
    return AccountDeletionResult.model_validate(result)
