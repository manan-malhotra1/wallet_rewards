"""Commission batch workflow — create, list, approve, reject (spec 2026-08-26 §8).

Mirrors `money_operations/service.py`: N-eyes quorum DERIVED from an
append-only review thread, self-approval refused, and the terminal status
staged BEFORE the money moves so both land in one commit.

Per the repo's existing convention (`money_operations` and `user_operations`
each carry their own copies), the review helpers live here rather than in a
shared module. Unifying all three is a separate refactor.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.commission_batches.apply import apply_batch
from app.modules.commission_batches.csv_io import (
    ParsedRow,
    parse_batch_csv,
    render_rejects_csv,
)
from app.modules.commission_batches.validation import ValidatedRow, validate_rows
from app.shared.exceptions import (
    AppHTTPException,
    BatchDuplicateApprover,
    BatchInvalidState,
    BatchNotFound,
    SelfApprovalForbidden,
)
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    BATCH_OPERATION,
    BATCH_STATUS_PENDING,
    BATCH_STATUS_REJECTED,
    BATCH_TYPE_WITHDRAWAL,
    REVIEW_APPROVED,
    REVIEW_REJECTED,
    ROW_STATUS_FAILED,
    ROW_STATUS_REJECTED,
    ROW_STATUS_VALID,
    Account,
    ApprovalPolicy,
    CommissionBatch,
    CommissionBatchReview,
    CommissionBatchRow,
)

# A single upload is parsed in-request, so it needs a bound (spec R6). Above
# this the operator splits the file rather than the request timing out.
MAX_BATCH_ROWS = 5000


async def _resolve_required_approvals(
    session: AsyncSession, tenant_id: UUID, operation: str
) -> int:
    """DISTINCT-approvals requirement for a (tenant, operation).

    Same resolution order as money_operations: an operation-specific policy
    wins; else the tenant-wide default; else 1 (four-eyes).
    """
    policies = (
        (
            await session.execute(
                select(ApprovalPolicy).where(
                    ApprovalPolicy.tenant_id == tenant_id,
                    or_(
                        ApprovalPolicy.operation == operation,
                        ApprovalPolicy.operation.is_(None),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    op_specific = next((p for p in policies if p.operation == operation), None)
    if op_specific is not None:
        return op_specific.required_approvals
    tenant_default = next((p for p in policies if p.operation is None), None)
    if tenant_default is not None:
        return tenant_default.required_approvals
    return 1


async def load_reviews(
    session: AsyncSession, batch_id: UUID
) -> list[CommissionBatchReview]:
    """The batch's append-only review thread, oldest first."""
    return list(
        (
            await session.execute(
                select(CommissionBatchReview)
                .where(CommissionBatchReview.batch_id == batch_id)
                .order_by(CommissionBatchReview.created_at)
            )
        )
        .scalars()
        .all()
    )


def distinct_approver_ids(reviews: list[CommissionBatchReview]) -> set[str]:
    """Admin ids that have APPROVED — the quorum count, derived not stored."""
    return {r.admin_id for r in reviews if r.decision == REVIEW_APPROVED}


async def _load_batch(
    session: AsyncSession, batch_id: UUID, tenant_id: UUID
) -> CommissionBatch:
    """Fetch a batch inside its tenant, or 404 (no cross-tenant existence leak)."""
    batch = (
        await session.execute(
            select(CommissionBatch).where(
                CommissionBatch.id == batch_id,
                CommissionBatch.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise BatchNotFound()
    return batch


async def _assert_bank_mirror(
    session: AsyncSession, tenant_id: UUID, account_id: UUID | None
) -> None:
    """A withdrawal must name a real operator_adjustment mirror in this tenant."""
    if account_id is None:
        raise AppHTTPException(
            422,
            "bank_mirror_required",
            "A withdrawal batch must name a destination bank mirror.",
        )
    account = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise AppHTTPException(
            422,
            "bank_mirror_not_found",
            "The destination account is not a bank mirror in this tenant.",
        )


def _row_from(validated: ValidatedRow, batch_id: UUID) -> CommissionBatchRow:
    """Build a persisted row from a validation result.

    Rejected rows are PERSISTED, not discarded — the maker downloads them as a
    rejects CSV (D15). The checker's queries filter to `valid`, so a reject
    never reaches an approver.
    """
    parsed = validated.parsed
    return CommissionBatchRow(
        batch_id=batch_id,
        row_number=parsed.row_number,
        msisdn=parsed.msisdn,
        currency=parsed.currency,
        # A row rejected for an unparseable amount still needs a NOT NULL
        # value; zero is the honest placeholder and never posts, because only
        # `valid` rows are applied.
        amount=parsed.amount if parsed.amount is not None else Decimal("0"),
        note=parsed.note,
        resolved_user_id=validated.resolved_user_id,
        resolved_account_id=validated.resolved_account_id,
        balance_snapshot=validated.balance_snapshot,
        snapshot_at=validated.snapshot_at,
        status=ROW_STATUS_VALID
        if validated.failure_reason is None
        else ROW_STATUS_REJECTED,
        failure_reason=validated.failure_reason,
    )


async def create_batch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    batch_type: str,
    file_name: str,
    content: str,
    admin: AdminPrincipal,
    destination_account_id: UUID | None = None,
    ip_address: str | None = None,
) -> CommissionBatch:
    """Parse, validate and stage an uploaded batch (spec §8.2).

    Args:
        tenant_id: Tenant scope, from the admin's token.
        batch_type: 'disbursement' or 'withdrawal'.
        file_name: As uploaded, for the audit trail.
        content: The decoded CSV body.
        admin: The maker.
        destination_account_id: Withdrawal only — the named bank mirror.

    Returns:
        The staged PENDING batch.

    Raises:
        AppHTTPException 422 `batch_file_invalid`: structurally unusable file.
        AppHTTPException 422 `batch_too_large`: above MAX_BATCH_ROWS.
        AppHTTPException 422 `batch_no_valid_rows`: nothing survived validation,
            so there would be nothing for a checker to approve.
        AppHTTPException 422 `bank_mirror_required` / `bank_mirror_not_found`.

    Side effects:
        Inserts one CommissionBatch, N CommissionBatchRow and one audit row.
        Commits once.
    """
    if batch_type == BATCH_TYPE_WITHDRAWAL:
        await _assert_bank_mirror(session, tenant_id, destination_account_id)
    else:
        destination_account_id = None

    try:
        parsed: list[ParsedRow] = parse_batch_csv(content)
    except ValueError as exc:
        raise AppHTTPException(422, "batch_file_invalid", str(exc)) from exc

    if len(parsed) > MAX_BATCH_ROWS:
        raise AppHTTPException(
            422,
            "batch_too_large",
            f"A batch may hold at most {MAX_BATCH_ROWS} rows; this file has {len(parsed)}.",
        )

    validated = await validate_rows(session, tenant_id=tenant_id, rows=parsed)
    valid = [v for v in validated if v.failure_reason is None]
    if not valid:
        raise AppHTTPException(
            422,
            "batch_no_valid_rows",
            "No row in this file could be paid. Fix the errors and re-upload.",
        )

    required = await _resolve_required_approvals(
        session, tenant_id, BATCH_OPERATION[batch_type]
    )
    batch = CommissionBatch(
        tenant_id=tenant_id,
        batch_type=batch_type,
        status=BATCH_STATUS_PENDING,
        file_name=file_name,
        row_count_total=len(validated),
        row_count_valid=len(valid),
        amount_total=sum(
            (v.parsed.amount for v in valid if v.parsed.amount is not None),
            Decimal("0"),
        ),
        destination_account_id=destination_account_id,
        created_by_admin_id=admin.id,
        required_approvals=required,
    )
    session.add(batch)
    await session.flush()

    for item in validated:
        session.add(_row_from(item, batch.id))

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="commission_batch.created",
        entity_type="commission_batch",
        entity_id=str(batch.id),
        after_state={
            "batch_type": batch_type,
            "file_name": file_name,
            "row_count_total": batch.row_count_total,
            "row_count_valid": batch.row_count_valid,
            "amount_total": str(batch.amount_total),
        },
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(batch)
    return batch


def _add_review(
    session: AsyncSession,
    batch: CommissionBatch,
    *,
    admin_id: str,
    decision: str,
    comment: str | None,
) -> None:
    """Append one immutable review row."""
    session.add(
        CommissionBatchReview(
            batch_id=batch.id,
            admin_id=admin_id,
            decision=decision,
            comment=comment,
        )
    )


async def approve_batch(
    session: AsyncSession,
    batch_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> CommissionBatch:
    """Checker approves; applies once N DISTINCT approvals land (spec §8.4).

    The terminal status is staged by `apply_batch` BEFORE this commits, so the
    transition and the postings land together — a failure inside apply rolls
    the approval back too, exactly as money_operations does.

    Raises:
        BatchNotFound: 404.
        BatchInvalidState: 409 — the batch is not PENDING.
        SelfApprovalForbidden: 409 — the approver is the maker.
        BatchDuplicateApprover: 409 — this admin already approved.
    """
    batch = await _load_batch(session, batch_id, tenant_id)
    if batch.status != BATCH_STATUS_PENDING:
        raise BatchInvalidState(batch.status)
    if admin.id == batch.created_by_admin_id:
        raise SelfApprovalForbidden()

    approvers = distinct_approver_ids(await load_reviews(session, batch.id))
    if admin.id in approvers:
        raise BatchDuplicateApprover()

    _add_review(
        session, batch, admin_id=admin.id, decision=REVIEW_APPROVED, comment=None
    )
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="commission_batch.approved",
        entity_type="commission_batch",
        entity_id=str(batch.id),
        ip_address=ip_address,
    )

    if len(approvers | {admin.id}) >= batch.required_approvals:
        await apply_batch(session, batch)
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="commission_batch.applied",
            entity_type="commission_batch",
            entity_id=str(batch.id),
            after_state={"status": batch.status},
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(batch)
    return batch


async def reject_batch(
    session: AsyncSession,
    batch_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    comment: str,
    ip_address: str | None = None,
) -> CommissionBatch:
    """Checker rejects the WHOLE batch. Terminal — the maker re-uploads (D16).

    Raises:
        BatchNotFound: 404.
        BatchInvalidState: 409 — the batch is not PENDING.
        AppHTTPException 422: the comment is empty. A rejection without a reason
            gives the maker nothing to correct.
    """
    if not comment or not comment.strip():
        raise AppHTTPException(
            422, "reject_comment_required", "A rejection must explain what to fix."
        )

    batch = await _load_batch(session, batch_id, tenant_id)
    if batch.status != BATCH_STATUS_PENDING:
        raise BatchInvalidState(batch.status)

    batch.status = BATCH_STATUS_REJECTED
    _add_review(
        session, batch, admin_id=admin.id, decision=REVIEW_REJECTED, comment=comment
    )
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="commission_batch.rejected",
        entity_type="commission_batch",
        entity_id=str(batch.id),
        after_state={"comment": comment},
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def list_batches(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    batch_type: str | None = None,
    status: str | None = None,
) -> list[CommissionBatch]:
    """Batches in a tenant, newest first, optionally filtered."""
    stmt = select(CommissionBatch).where(CommissionBatch.tenant_id == tenant_id)
    if batch_type is not None:
        stmt = stmt.where(CommissionBatch.batch_type == batch_type)
    if status is not None:
        stmt = stmt.where(CommissionBatch.status == status)
    stmt = stmt.order_by(CommissionBatch.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_batch_rows(
    session: AsyncSession, batch_id: UUID
) -> list[CommissionBatchRow]:
    """Every row of a batch, in file order."""
    return list(
        (
            await session.execute(
                select(CommissionBatchRow)
                .where(CommissionBatchRow.batch_id == batch_id)
                .order_by(CommissionBatchRow.row_number)
            )
        )
        .scalars()
        .all()
    )


async def get_batch_detail(
    session: AsyncSession, batch_id: UUID, tenant_id: UUID
) -> tuple[CommissionBatch, list[CommissionBatchRow], int]:
    """A batch, its rows and its live approval count."""
    batch = await _load_batch(session, batch_id, tenant_id)
    rows = await get_batch_rows(session, batch.id)
    approvals = len(distinct_approver_ids(await load_reviews(session, batch.id)))
    return batch, rows, approvals


async def get_batch_rejects_csv(
    session: AsyncSession, batch_id: UUID, tenant_id: UUID
) -> str:
    """This batch's unpayable rows as a downloadable CSV (spec §8.2).

    Covers BOTH reject passes: rows rejected at upload (`rejected`) and rows
    that failed at apply because the balance moved (`failed`). The maker fixes
    either kind the same way — correct the data, upload a NEW batch.
    """
    await _load_batch(session, batch_id, tenant_id)
    rows = [
        row
        for row in await get_batch_rows(session, batch_id)
        if row.status in (ROW_STATUS_REJECTED, ROW_STATUS_FAILED)
    ]
    return render_rejects_csv(
        [
            (
                ParsedRow(
                    row_number=row.row_number,
                    msisdn=row.msisdn,
                    currency=row.currency,
                    amount=Decimal(str(row.amount)),
                    note=row.note,
                ),
                row.failure_reason or "unknown",
            )
            for row in rows
        ]
    )
