"""Commission batch FastAPI router — spec 2026-08-26 §8, §11.

Two operator menus over one module: makers (platform-admin) upload a CSV;
checkers (treasury-approver) approve or reject the whole batch. `tenant_id` is
an explicit query param because admins are cross-tenant, matching the
money-operations and config-requests routers.

Routers contain no business logic (invariant #5) — every endpoint parses, then
calls exactly one service function.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.commission_batches.schemas import (
    BatchOut,
    BatchRejectRequest,
    BatchRowOut,
    BatchType,
)
from app.modules.commission_batches.service import (
    approve_batch,
    create_batch,
    distinct_approver_ids,
    get_batch_detail,
    get_batch_rejects_csv,
    list_batches,
    load_reviews,
    reject_batch,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import CommissionBatch, CommissionBatchRow

router = APIRouter(prefix="/api/v1/commission-batches", tags=["commission-batches"])

# 5,000 rows of `msisdn,currency,amount,note` sits well under this; the cap is
# a guard against an accidental multi-hundred-MB upload, not a row limit (the
# row limit lives in the service).
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _row_out(row: CommissionBatchRow) -> BatchRowOut:
    """Project a row, computing the checker's delta.

    `delta` is balance minus amount — how much accrued commission this run is
    NOT moving. It is None when no balance was resolved (a rejected row).
    """
    balance = (
        Decimal(str(row.balance_snapshot)) if row.balance_snapshot is not None else None
    )
    amount = Decimal(str(row.amount))
    return BatchRowOut(
        id=row.id,
        row_number=row.row_number,
        msisdn=row.msisdn,
        currency=row.currency,
        amount=amount,
        note=row.note,
        balance_snapshot=balance,
        snapshot_at=row.snapshot_at,
        delta=None if balance is None else balance - amount,
        status=row.status,
        failure_reason=row.failure_reason,
        transaction_id=row.transaction_id,
    )


def _batch_out(
    batch: CommissionBatch,
    rows: list[CommissionBatchRow],
    approvals_received: int,
) -> BatchOut:
    """Project a batch header plus its rows."""
    return BatchOut(
        id=batch.id,
        tenant_id=batch.tenant_id,
        batch_type=batch.batch_type,
        status=batch.status,
        file_name=batch.file_name,
        row_count_total=batch.row_count_total,
        row_count_valid=batch.row_count_valid,
        amount_total=Decimal(str(batch.amount_total)),
        destination_account_id=batch.destination_account_id,
        created_by_admin_id=batch.created_by_admin_id,
        required_approvals=batch.required_approvals,
        approvals_received=approvals_received,
        created_at=batch.created_at,
        rows=[_row_out(r) for r in rows],
    )


@router.post("", response_model=BatchOut, status_code=201)
async def upload_batch(
    request: Request,
    tenant_id: UUID = Query(...),
    # Validated as a Literal rather than a bare str: the service indexes
    # BATCH_OPERATION by this value, so an unvalidated string would KeyError
    # into a 500 instead of a clean 422.
    batch_type: BatchType = Form(...),
    destination_account_id: UUID | None = Form(default=None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> BatchOut:
    """Upload and stage a commission batch (maker)."""
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise AppHTTPException(
            422, "batch_file_too_large", "The uploaded file is too large."
        )
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppHTTPException(
            422, "batch_file_invalid", "The file must be UTF-8 encoded CSV."
        ) from exc

    batch = await create_batch(
        session,
        tenant_id=tenant_id,
        batch_type=batch_type,
        file_name=file.filename or "batch.csv",
        content=content,
        admin=admin,
        destination_account_id=destination_account_id,
        ip_address=request.client.host if request.client else None,
    )
    _, rows, approvals = await get_batch_detail(session, batch.id, tenant_id)
    return _batch_out(batch, rows, approvals)


@router.get("", response_model=list[BatchOut])
async def list_commission_batches(
    tenant_id: UUID = Query(...),
    batch_type: BatchType | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> list[BatchOut]:
    """List batches in a tenant, newest first. Headers only — no rows."""
    batches = await list_batches(
        session, tenant_id, batch_type=batch_type, status=status
    )
    out: list[BatchOut] = []
    for batch in batches:
        approvals = len(distinct_approver_ids(await load_reviews(session, batch.id)))
        out.append(_batch_out(batch, [], approvals))
    return out


@router.get("/{batch_id}", response_model=BatchOut)
async def get_commission_batch(
    batch_id: UUID,
    tenant_id: UUID = Query(...),
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> BatchOut:
    """One batch with its rows — the checker's review screen."""
    batch, rows, approvals = await get_batch_detail(session, batch_id, tenant_id)
    return _batch_out(batch, rows, approvals)


@router.get("/{batch_id}/rejects", response_class=PlainTextResponse)
async def download_rejects(
    batch_id: UUID,
    tenant_id: UUID = Query(...),
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> PlainTextResponse:
    """Unpayable rows as a re-uploadable CSV (both reject passes)."""
    body = await get_batch_rejects_csv(session, batch_id, tenant_id)
    return PlainTextResponse(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="rejects-{batch_id}.csv"'
        },
    )


@router.post("/{batch_id}/approve", response_model=BatchOut)
async def approve_commission_batch(
    batch_id: UUID,
    request: Request,
    tenant_id: UUID = Query(...),
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("treasury-approver")),
) -> BatchOut:
    """Approve a batch; applies once quorum is reached (checker)."""
    batch = await approve_batch(
        session,
        batch_id,
        tenant_id,
        admin=admin,
        ip_address=request.client.host if request.client else None,
    )
    _, rows, approvals = await get_batch_detail(session, batch.id, tenant_id)
    return _batch_out(batch, rows, approvals)


@router.post("/{batch_id}/reject", response_model=BatchOut)
async def reject_commission_batch(
    batch_id: UUID,
    payload: BatchRejectRequest,
    request: Request,
    tenant_id: UUID = Query(...),
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("treasury-approver")),
) -> BatchOut:
    """Reject the WHOLE batch with a mandatory comment. Terminal (D16)."""
    batch = await reject_batch(
        session,
        batch_id,
        tenant_id,
        admin=admin,
        comment=payload.comment,
        ip_address=request.client.host if request.client else None,
    )
    _, rows, approvals = await get_batch_detail(session, batch.id, tenant_id)
    return _batch_out(batch, rows, approvals)
