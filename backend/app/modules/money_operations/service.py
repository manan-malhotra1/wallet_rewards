"""Money-operation maker-checker service — N-eyes control (Epic 18).

Propose → (approve* | request-changes → revise → resubmit)* → APPLIED, or
withdraw. Nothing hits the ledger until `required_approvals` DISTINCT checker
approvals land in the current round; the request row and its append-only review
thread persist across the whole loop.

Separation of duties (mirrors config_requests): the maker who proposed may never
approve their own request, and each required approval must come from a DISTINCT
admin. Revise / resubmit / withdraw are the ORIGINAL maker only.

N-eyes counting, distinct-approver, and reset-on-resubmit all derive from the
review thread: the "current round" is every review AFTER the latest `resubmitted`
entry (all reviews when there has been no resubmit). A resubmit therefore starts
a fresh round — earlier approvals no longer count and an admin who approved a
prior round may approve again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.admin_profiles import record_admin
from app.modules.audit.service import record_audit_for_admin
from app.modules.money_operations.apply import apply_money_operation
from app.modules.money_operations.schemas import PAYLOAD_SCHEMAS
from app.shared.exceptions import (
    AppHTTPException,
    MoneyOperationDuplicateApprover,
    MoneyOperationForbidden,
    MoneyOperationInvalidState,
    MoneyOperationNotFound,
    SelfApprovalForbidden,
    TenantNotFound,
)
from app.shared.models import (
    MONEY_OP_STATUS_APPLIED,
    MONEY_OP_STATUS_CHANGES_REQUESTED,
    MONEY_OP_STATUS_PENDING,
    MONEY_OP_STATUS_WITHDRAWN,
    MONEY_OP_STATUSES,
    MONEY_OP_TERMINAL_STATUSES,
    MONEY_REVIEW_ACTION_APPLIED,
    MONEY_REVIEW_ACTION_APPROVED,
    MONEY_REVIEW_ACTION_CHANGES_REQUESTED,
    MONEY_REVIEW_ACTION_RESUBMITTED,
    MONEY_REVIEW_ACTION_REVISED,
    MONEY_REVIEW_ACTION_SUBMITTED,
    MONEY_REVIEW_ACTION_WITHDRAWN,
    MONEY_REVIEW_ROLE_CHECKER,
    MONEY_REVIEW_ROLE_MAKER,
    ApprovalPolicy,
    MoneyOperationRequest,
    MoneyOperationReview,
    Tenant,
)
from app.shared.queue_counts import (
    QueueCountsOut,
    apply_newest_first_window,
    count_queue_by_status,
)

# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _load_request(
    session: AsyncSession, request_id: UUID, tenant_id: UUID, *, for_update: bool = False
) -> MoneyOperationRequest:
    """Load a tenant-scoped request, optionally locking it for a state change."""
    stmt = select(MoneyOperationRequest).where(
        MoneyOperationRequest.id == request_id,
        MoneyOperationRequest.tenant_id == tenant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    request = result.scalar_one_or_none()
    if request is None:
        raise MoneyOperationNotFound()
    return request


async def load_reviews(session: AsyncSession, request_id: UUID) -> list[MoneyOperationReview]:
    """Return a request's review thread, oldest-first (append-only)."""
    result = await session.execute(
        select(MoneyOperationReview)
        .where(MoneyOperationReview.request_id == request_id)
        .order_by(MoneyOperationReview.created_at.asc(), MoneyOperationReview.id.asc())
    )
    return list(result.scalars().all())


def _current_round(reviews: list[MoneyOperationReview]) -> list[MoneyOperationReview]:
    """Return the reviews in the CURRENT approval round.

    The current round is every review after the LATEST `resubmitted` entry (a
    resubmit starts a fresh round). With no resubmit, the round is the whole
    thread. `reviews` must be ordered oldest-first.
    """
    last_resubmit = -1
    for i, review in enumerate(reviews):
        if review.action == MONEY_REVIEW_ACTION_RESUBMITTED:
            last_resubmit = i
    return reviews[last_resubmit + 1 :]


def distinct_approver_ids(reviews: list[MoneyOperationReview]) -> set[str]:
    """Return the DISTINCT admin ids that approved in the current round.

    Drives both the N-eyes count and the duplicate-approver guard. `reviews`
    must be ordered oldest-first (as `load_reviews` returns them).
    """
    return {
        review.actor_admin_id
        for review in _current_round(reviews)
        if review.action == MONEY_REVIEW_ACTION_APPROVED
    }


def _add_review(
    session: AsyncSession,
    request: MoneyOperationRequest,
    *,
    actor_admin_id: str,
    actor_role: str,
    action: str,
    comment: str | None = None,
) -> None:
    """Append one entry to the request's review thread (append-only).

    Stamps `created_at` in Python (not the DB default) so two reviews appended
    in the SAME transaction — e.g. `approved` then `applied` on the quorum
    approval — get strictly increasing timestamps and the thread orders
    deterministically by insertion (the query sorts by created_at, id).
    """
    session.add(
        MoneyOperationReview(
            tenant_id=request.tenant_id,
            request_id=request.id,
            actor_admin_id=actor_admin_id,
            actor_role=actor_role,
            action=action,
            comment=comment,
            created_at=datetime.now(UTC),
        )
    )


def _audit(
    session: AsyncSession,
    admin: AdminPrincipal,
    request: MoneyOperationRequest,
    action: str,
    ip_address: str | None,
) -> None:
    """Record an admin audit row for a money-operation transition."""
    record_audit_for_admin(
        session,
        admin,
        tenant_id=request.tenant_id,
        action=action,
        entity_type="money_operation_request",
        entity_id=str(request.id),
        after_state={
            "operation": request.operation,
            "status": request.status,
            "required_approvals": request.required_approvals,
        },
        ip_address=ip_address,
    )


def _validate_payload(operation: str, payload: dict[str, object]) -> dict[str, object]:
    """Validate `payload` against `operation`'s schema; return the JSON-safe form.

    The normalised (model_dump mode="json") dict is what gets stored in JSONB —
    Decimals/UUIDs become strings so asyncpg can serialise them, and apply
    re-parses them back through the same schema.

    Raises:
        AppHTTPException (422): unknown operation, or a payload that fails its
            schema.
    """
    schema_cls = PAYLOAD_SCHEMAS.get(operation)
    if schema_cls is None:
        raise AppHTTPException(
            422,
            "money_operation_invalid_operation",
            f"'{operation}' is not a recognised money operation.",
        )
    try:
        model = schema_cls.model_validate(payload)
    except ValidationError as exc:
        raise AppHTTPException(
            422,
            "money_operation_invalid_payload",
            f"Payload is not a valid {operation} operation: {exc}",
        ) from exc
    return model.model_dump(mode="json")


async def _resolve_required_approvals(
    session: AsyncSession, tenant_id: UUID, operation: str
) -> int:
    """Resolve the DISTINCT-approvals requirement for a (tenant, operation).

    Resolution order: an operation-specific ApprovalPolicy row wins; else the
    tenant-wide default (operation IS NULL); else a code default of 1
    (four-eyes: maker + 1 checker).
    """
    result = await session.execute(
        select(ApprovalPolicy).where(
            ApprovalPolicy.tenant_id == tenant_id,
            or_(ApprovalPolicy.operation == operation, ApprovalPolicy.operation.is_(None)),
        )
    )
    policies = result.scalars().all()
    op_specific = next((p for p in policies if p.operation == operation), None)
    if op_specific is not None:
        return op_specific.required_approvals
    tenant_default = next((p for p in policies if p.operation is None), None)
    if tenant_default is not None:
        return tenant_default.required_approvals
    return 1


# -----------------------------------------------------------------------------
# Workflow operations
# -----------------------------------------------------------------------------


async def propose_money_operation(
    session: AsyncSession,
    *,
    operation: str,
    payload: dict[str, object],
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Maker proposes a money operation → PENDING, no money moved yet.

    The payload is validated against the operation's schema, `required_approvals`
    is resolved from ApprovalPolicy, and the request is created PENDING with a
    `submitted` review. Nothing executes until enough distinct approvals land.

    Raises:
        TenantNotFound (404).
        AppHTTPException (422): unknown operation or invalid payload.
    """
    await _assert_tenant_exists(session, tenant_id)
    normalised = _validate_payload(operation, payload)
    required_approvals = await _resolve_required_approvals(session, tenant_id, operation)

    request = MoneyOperationRequest(
        tenant_id=tenant_id,
        operation=operation,
        payload=normalised,
        status=MONEY_OP_STATUS_PENDING,
        maker_admin_id=admin.id,
        required_approvals=required_approvals,
    )
    session.add(request)
    await session.flush()
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=MONEY_REVIEW_ROLE_MAKER,
        action=MONEY_REVIEW_ACTION_SUBMITTED,
    )
    _audit(session, admin, request, "money_op.proposed", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def approve_money_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Checker approves a PENDING request; applies once N distinct approvals land.

    Records the approval, then recomputes the DISTINCT approvers in the current
    round. When that count reaches `required_approvals`, the request is staged
    APPLIED (with an `applied` review + audit) BEFORE `apply_money_operation`
    runs — so the staged transition and the treasury execution commit together
    (mirrors config_requests.approve). Otherwise the request stays PENDING with
    the approval recorded as progress.

    Raises:
        MoneyOperationNotFound (404).
        MoneyOperationInvalidState (409): the request isn't PENDING.
        SelfApprovalForbidden (409): the approver is the maker.
        MoneyOperationDuplicateApprover (409): this admin already approved in the
            current round.
        AppHTTPException: propagated from the treasury execution, rolling the
            whole transaction (approval + apply) back.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != MONEY_OP_STATUS_PENDING:
        raise MoneyOperationInvalidState(request.status)
    if admin.id == request.maker_admin_id:
        raise SelfApprovalForbidden()

    reviews = await load_reviews(session, request.id)
    approvers = distinct_approver_ids(reviews)
    if admin.id in approvers:
        raise MoneyOperationDuplicateApprover()

    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=MONEY_REVIEW_ROLE_CHECKER,
        action=MONEY_REVIEW_ACTION_APPROVED,
    )
    _audit(session, admin, request, "money_op.approved", ip_address)

    approvers = approvers | {admin.id}
    if len(approvers) >= request.required_approvals:
        # Quorum reached — stage APPLIED + the applied review/audit BEFORE the
        # treasury execution so both land in the treasury fn's single commit.
        request.status = MONEY_OP_STATUS_APPLIED
        _add_review(
            session,
            request,
            actor_admin_id=admin.id,
            actor_role=MONEY_REVIEW_ROLE_CHECKER,
            action=MONEY_REVIEW_ACTION_APPLIED,
        )
        _audit(session, admin, request, "money_op.applied", ip_address)
        await record_admin(session, admin)
        await apply_money_operation(session, request, ip_address=ip_address)
        await session.refresh(request)
        return request

    # Not yet at quorum — persist the approval as progress; still PENDING.
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def request_money_op_changes(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    comment: str,
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Checker requests changes on a PENDING request → CHANGES_REQUESTED.

    Raises:
        MoneyOperationNotFound (404).
        MoneyOperationInvalidState (409): the request isn't PENDING.
        SelfApprovalForbidden (409): the checker is the maker.
        AppHTTPException (422): a blank comment (the router schema also enforces
            this, but the service fails closed too).
    """
    if not comment.strip():
        raise AppHTTPException(
            422,
            "money_operation_comment_required",
            "A comment is required when requesting changes.",
        )
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != MONEY_OP_STATUS_PENDING:
        raise MoneyOperationInvalidState(request.status)
    if admin.id == request.maker_admin_id:
        raise SelfApprovalForbidden()

    request.status = MONEY_OP_STATUS_CHANGES_REQUESTED
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=MONEY_REVIEW_ROLE_CHECKER,
        action=MONEY_REVIEW_ACTION_CHANGES_REQUESTED,
        comment=comment,
    )
    _audit(session, admin, request, "money_op.changes_requested", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def revise_money_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    payload: dict[str, object],
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Original maker edits a CHANGES_REQUESTED request's payload in place.

    Stays CHANGES_REQUESTED (the maker resubmits separately). The new payload is
    re-validated against the operation's schema exactly like propose.

    Raises:
        MoneyOperationNotFound (404).
        MoneyOperationForbidden (403): not the original maker.
        MoneyOperationInvalidState (409): not in CHANGES_REQUESTED.
        AppHTTPException (422): the new payload fails its schema.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != MONEY_OP_STATUS_CHANGES_REQUESTED:
        raise MoneyOperationInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise MoneyOperationForbidden("Only the original maker may revise this request.")

    request.payload = _validate_payload(request.operation, payload)
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=MONEY_REVIEW_ROLE_MAKER,
        action=MONEY_REVIEW_ACTION_REVISED,
    )
    _audit(session, admin, request, "money_op.revised", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def resubmit_money_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Original maker resubmits a CHANGES_REQUESTED request → PENDING.

    A resubmit starts a fresh approval round: any approvals recorded before it no
    longer count (the distinct-approver + N-eyes logic reads only reviews after
    the latest `resubmitted`).

    Raises:
        MoneyOperationNotFound (404).
        MoneyOperationForbidden (403): not the original maker.
        MoneyOperationInvalidState (409): not in CHANGES_REQUESTED.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != MONEY_OP_STATUS_CHANGES_REQUESTED:
        raise MoneyOperationInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise MoneyOperationForbidden("Only the original maker may resubmit this request.")

    request.status = MONEY_OP_STATUS_PENDING
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=MONEY_REVIEW_ROLE_MAKER,
        action=MONEY_REVIEW_ACTION_RESUBMITTED,
    )
    _audit(session, admin, request, "money_op.resubmitted", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def withdraw_money_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Original maker abandons a non-terminal request → WITHDRAWN (terminal).

    Raises:
        MoneyOperationNotFound (404).
        MoneyOperationForbidden (403): not the original maker.
        MoneyOperationInvalidState (409): the request is already terminal.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status in MONEY_OP_TERMINAL_STATUSES:
        raise MoneyOperationInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise MoneyOperationForbidden("Only the original maker may withdraw this request.")

    request.status = MONEY_OP_STATUS_WITHDRAWN
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=MONEY_REVIEW_ROLE_MAKER,
        action=MONEY_REVIEW_ACTION_WITHDRAWN,
    )
    _audit(session, admin, request, "money_op.withdrawn", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def list_money_operations(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[MoneyOperationRequest]:
    """Return a tenant's money-operation requests, newest-first, optionally by status.

    Args:
        limit: Maximum rows to return; None means unbounded (existing callers).
        offset: Rows to skip before the window starts (B7.1 pagination). The
            ordering tie-breaks on id so a fixed window never duplicates or
            drops rows created in the same instant.
    """
    stmt = select(MoneyOperationRequest).where(MoneyOperationRequest.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(MoneyOperationRequest.status == status)
    stmt = apply_newest_first_window(stmt, MoneyOperationRequest, limit=limit, offset=offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_money_operations(session: AsyncSession, tenant_id: UUID) -> QueueCountsOut:
    """Count a tenant's money operations per status in one grouped query (no rows)."""
    return await count_queue_by_status(session, MoneyOperationRequest, tenant_id, MONEY_OP_STATUSES)


async def get_money_operation(
    session: AsyncSession, request_id: UUID, tenant_id: UUID
) -> tuple[MoneyOperationRequest, list[MoneyOperationReview]]:
    """Return a request with its review thread (oldest-first)."""
    request = await _load_request(session, request_id, tenant_id)
    reviews = await load_reviews(session, request.id)
    return request, reviews
