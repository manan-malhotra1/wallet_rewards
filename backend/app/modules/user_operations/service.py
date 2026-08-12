"""User-operation maker-checker service — N-eyes control for admin user ops.

Propose → (approve* | request-changes → revise → resubmit)* → APPLIED, or
withdraw. Nothing is created or edited until `required_approvals` DISTINCT
checker approvals land in the current round; the request row and its append-only
review thread persist across the whole loop.

Separation of duties (mirrors money_operations): the maker who proposed may never
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

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.admin_profiles import record_admin
from app.modules.audit.service import record_audit_for_admin
from app.modules.identity.service import _find_identifier
from app.modules.user_operations.apply import apply_user_operation
from app.modules.user_operations.schemas import (
    PAYLOAD_SCHEMAS,
    CreateUserPayload,
    UpdateUserPayload,
)
from app.shared.exceptions import (
    AppHTTPException,
    IdentifierAlreadyInUse,
    SelfApprovalForbidden,
    TenantNotFound,
    UserNotFound,
    UserOperationDuplicateApprover,
    UserOperationForbidden,
    UserOperationInvalidState,
    UserOperationNotFound,
)
from app.shared.models import (
    USER_OP_CREATE,
    USER_OP_STATUS_APPLIED,
    USER_OP_STATUS_CHANGES_REQUESTED,
    USER_OP_STATUS_PENDING,
    USER_OP_STATUS_WITHDRAWN,
    USER_OP_TERMINAL_STATUSES,
    USER_OP_UPDATE,
    USER_REVIEW_ACTION_APPLIED,
    USER_REVIEW_ACTION_APPROVED,
    USER_REVIEW_ACTION_CHANGES_REQUESTED,
    USER_REVIEW_ACTION_RESUBMITTED,
    USER_REVIEW_ACTION_REVISED,
    USER_REVIEW_ACTION_SUBMITTED,
    USER_REVIEW_ACTION_WITHDRAWN,
    USER_REVIEW_ROLE_CHECKER,
    USER_REVIEW_ROLE_MAKER,
    Tenant,
    User,
    UserOperationRequest,
    UserOperationReview,
)
from app.shared.utils.normalize import normalize_identifier

log = structlog.get_logger()

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
) -> UserOperationRequest:
    """Load a tenant-scoped request, optionally locking it for a state change."""
    stmt = select(UserOperationRequest).where(
        UserOperationRequest.id == request_id,
        UserOperationRequest.tenant_id == tenant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    request = result.scalar_one_or_none()
    if request is None:
        raise UserOperationNotFound()
    return request


async def load_reviews(session: AsyncSession, request_id: UUID) -> list[UserOperationReview]:
    """Return a request's review thread, oldest-first (append-only)."""
    result = await session.execute(
        select(UserOperationReview)
        .where(UserOperationReview.request_id == request_id)
        .order_by(UserOperationReview.created_at.asc(), UserOperationReview.id.asc())
    )
    return list(result.scalars().all())


def _current_round(reviews: list[UserOperationReview]) -> list[UserOperationReview]:
    """Return the reviews in the CURRENT approval round.

    The current round is every review after the LATEST `resubmitted` entry (a
    resubmit starts a fresh round). With no resubmit, the round is the whole
    thread. `reviews` must be ordered oldest-first.
    """
    last_resubmit = -1
    for i, review in enumerate(reviews):
        if review.action == USER_REVIEW_ACTION_RESUBMITTED:
            last_resubmit = i
    return reviews[last_resubmit + 1 :]


def distinct_approver_ids(reviews: list[UserOperationReview]) -> set[str]:
    """Return the DISTINCT admin ids that approved in the current round.

    Drives both the N-eyes count and the duplicate-approver guard. `reviews`
    must be ordered oldest-first (as `load_reviews` returns them).
    """
    return {
        review.actor_admin_id
        for review in _current_round(reviews)
        if review.action == USER_REVIEW_ACTION_APPROVED
    }


def _add_review(
    session: AsyncSession,
    request: UserOperationRequest,
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
        UserOperationReview(
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
    request: UserOperationRequest,
    action: str,
    ip_address: str | None,
) -> None:
    """Record an admin audit row for a user-operation transition."""
    record_audit_for_admin(
        session,
        admin,
        tenant_id=request.tenant_id,
        action=action,
        entity_type="user_operation_request",
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
    UUIDs become strings so asyncpg can serialise them, and apply re-parses them
    back through the same schema.

    Raises:
        AppHTTPException (422): unknown operation, or a payload that fails its
            schema.
    """
    schema_cls = PAYLOAD_SCHEMAS.get(operation)
    if schema_cls is None:
        raise AppHTTPException(
            422,
            "user_operation_invalid_operation",
            f"'{operation}' is not a recognised user operation.",
        )
    try:
        model = schema_cls.model_validate(payload)
    except ValidationError as exc:
        # The pydantic error string can echo the offending payload values back,
        # and a create_user payload carries PII (email/phone). Keep the detail
        # server-side only (structlog masks nothing, so log field names — never
        # the raw exc — in the response) per NFR-0170/NFR-0240. We surface the
        # invalid field *names* to the caller, not their values.
        invalid_fields = sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]})
        log.info(
            "user_operation_payload_invalid",
            operation=operation,
            error_count=exc.error_count(),
            invalid_fields=invalid_fields,
        )
        detail = (
            f"Payload is not a valid {operation} operation"
            + (f" (check: {', '.join(invalid_fields)})" if invalid_fields else "")
            + "."
        )
        raise AppHTTPException(
            422,
            "user_operation_invalid_payload",
            detail,
        ) from exc
    return model.model_dump(mode="json")


async def _assert_target_exists(
    session: AsyncSession, tenant_id: UUID, payload: dict[str, object]
) -> None:
    """Confirm an update_user target user exists in-tenant (404 otherwise).

    Raises:
        UserNotFound (404): the payload's target_user_id is unknown in this
            tenant (checked at propose time so a bad target fails fast).
    """
    target_id = UpdateUserPayload.model_validate(payload).target_user_id
    result = await session.execute(
        select(User).where(User.id == target_id, User.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise UserNotFound()


def _canonical_identifiers(payload: dict[str, object]) -> set[tuple[str, str]]:
    """Return a create_user payload's (type, canonical-value) identifier pairs.

    Values are run through `normalize_identifier` — the SAME helper
    `identity.create_user` applies before persistence — so propose-time
    comparisons use the exact canonical form apply will insert (spaces / dashes
    in a phone collapse to one representation, email lowercases).
    """
    identifiers = CreateUserPayload.model_validate(payload).identifiers
    return {
        (ident.identifier_type, normalize_identifier(ident.identifier_type, ident.identifier_value))
        for ident in identifiers
    }


async def _assert_create_identifiers_available(
    session: AsyncSession, tenant_id: UUID, payload: dict[str, object]
) -> None:
    """Confirm no create_user identifier is already taken in-tenant (409 otherwise).

    A `create_user` proposal must reject at propose time — not only at apply — if
    any of its identifiers is EITHER already owned by a live user, OR already the
    subject of another PENDING `create_user` proposal (so two proposals can't
    stack on the same phone). Comparison is on the canonical identifier form
    (`_canonical_identifiers`) so it agrees exactly with create_user's insert.

    Raises:
        IdentifierAlreadyInUse (409): a proposed identifier collides with a live
            user or another pending create_user proposal in this tenant.
    """
    proposed = _canonical_identifiers(payload)

    # (a) Already owned by a live user — reuse create_user's own lookup against
    # the same canonical value so propose-time and apply-time agree exactly.
    for identifier_type, canonical in proposed:
        if await _find_identifier(session, tenant_id, identifier_type, canonical) is not None:
            raise IdentifierAlreadyInUse(identifier_type)

    # (b) Already claimed by another PENDING create_user proposal in this tenant.
    result = await session.execute(
        select(UserOperationRequest).where(
            UserOperationRequest.tenant_id == tenant_id,
            UserOperationRequest.operation == USER_OP_CREATE,
            UserOperationRequest.status == USER_OP_STATUS_PENDING,
        )
    )
    for pending in result.scalars().all():
        for identifier_type, canonical in _canonical_identifiers(pending.payload):
            if (identifier_type, canonical) in proposed:
                raise IdentifierAlreadyInUse(identifier_type)


# -----------------------------------------------------------------------------
# Workflow operations
# -----------------------------------------------------------------------------


async def propose_user_operation(
    session: AsyncSession,
    *,
    operation: str,
    payload: dict[str, object],
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Maker proposes a user operation → PENDING, no user created/changed yet.

    The payload is validated against the operation's schema and, for update_user,
    the target user's existence in-tenant is confirmed; for create_user, every
    identifier is confirmed free (not owned by a live user, not already the
    subject of another pending create_user proposal). The request is created
    PENDING with a `submitted` review. Nothing applies until enough distinct
    approvals land.

    Raises:
        TenantNotFound (404).
        UserNotFound (404): update_user target is unknown in this tenant.
        IdentifierAlreadyInUse (409): a create_user identifier already belongs to
            a live user or another pending create_user proposal in this tenant.
        AppHTTPException (422): unknown operation or invalid payload.
    """
    await _assert_tenant_exists(session, tenant_id)
    normalised = _validate_payload(operation, payload)
    if operation == USER_OP_UPDATE:
        await _assert_target_exists(session, tenant_id, normalised)
    if operation == USER_OP_CREATE:
        await _assert_create_identifiers_available(session, tenant_id, normalised)

    request = UserOperationRequest(
        tenant_id=tenant_id,
        operation=operation,
        payload=normalised,
        status=USER_OP_STATUS_PENDING,
        maker_admin_id=admin.id,
        # User ops are four-eyes only for now (one distinct checker). There is no
        # per-operation approval policy table yet; the column/CHECK allow 2 so a
        # future policy can raise it, but no path sets it above 1 today.
        required_approvals=1,
    )
    session.add(request)
    await session.flush()
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=USER_REVIEW_ROLE_MAKER,
        action=USER_REVIEW_ACTION_SUBMITTED,
    )
    _audit(session, admin, request, "user_op.proposed", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def approve_user_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Checker approves a PENDING request; applies once N distinct approvals land.

    Records the approval, then recomputes the DISTINCT approvers in the current
    round. When that count reaches `required_approvals`, the request is staged
    APPLIED (with an `applied` review + audit) BEFORE `apply_user_operation`
    runs — so the staged transition and the identity change commit together.
    Otherwise the request stays PENDING with the approval recorded as progress.

    Raises:
        UserOperationNotFound (404).
        UserOperationInvalidState (409): the request isn't PENDING.
        SelfApprovalForbidden (409): the approver is the maker.
        UserOperationDuplicateApprover (409): this admin already approved in the
            current round.
        AppHTTPException: propagated from the identity apply, rolling the whole
            transaction (approval + apply) back.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != USER_OP_STATUS_PENDING:
        raise UserOperationInvalidState(request.status)
    if admin.id == request.maker_admin_id:
        raise SelfApprovalForbidden()

    reviews = await load_reviews(session, request.id)
    approvers = distinct_approver_ids(reviews)
    if admin.id in approvers:
        raise UserOperationDuplicateApprover()

    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=USER_REVIEW_ROLE_CHECKER,
        action=USER_REVIEW_ACTION_APPROVED,
    )
    _audit(session, admin, request, "user_op.approved", ip_address)

    approvers = approvers | {admin.id}
    if len(approvers) >= request.required_approvals:
        # Quorum reached — stage APPLIED + the applied review/audit BEFORE the
        # identity change so both land in the identity fn's single commit.
        request.status = USER_OP_STATUS_APPLIED
        _add_review(
            session,
            request,
            actor_admin_id=admin.id,
            actor_role=USER_REVIEW_ROLE_CHECKER,
            action=USER_REVIEW_ACTION_APPLIED,
        )
        _audit(session, admin, request, "user_op.applied", ip_address)
        await record_admin(session, admin)
        await apply_user_operation(session, request, ip_address=ip_address)
        await session.refresh(request)
        return request

    # Not yet at quorum — persist the approval as progress; still PENDING.
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def request_user_op_changes(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    comment: str,
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Checker requests changes on a PENDING request → CHANGES_REQUESTED.

    Raises:
        UserOperationNotFound (404).
        UserOperationInvalidState (409): the request isn't PENDING.
        SelfApprovalForbidden (409): the checker is the maker.
        AppHTTPException (422): a blank comment (the router schema also enforces
            this, but the service fails closed too).
    """
    if not comment.strip():
        raise AppHTTPException(
            422,
            "user_operation_comment_required",
            "A comment is required when requesting changes.",
        )
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != USER_OP_STATUS_PENDING:
        raise UserOperationInvalidState(request.status)
    if admin.id == request.maker_admin_id:
        raise SelfApprovalForbidden()

    request.status = USER_OP_STATUS_CHANGES_REQUESTED
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=USER_REVIEW_ROLE_CHECKER,
        action=USER_REVIEW_ACTION_CHANGES_REQUESTED,
        comment=comment,
    )
    _audit(session, admin, request, "user_op.changes_requested", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def revise_user_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    payload: dict[str, object],
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Original maker edits a CHANGES_REQUESTED request's payload in place.

    Stays CHANGES_REQUESTED (the maker resubmits separately). The new payload is
    re-validated against the operation's schema exactly like propose, an
    update_user target's existence is re-confirmed, and a create_user's revised
    identifiers are re-checked for availability — revise is a SECOND door into
    the approval loop and must enforce the same duplicate guard as propose.

    Raises:
        UserOperationNotFound (404).
        UserOperationForbidden (403): not the original maker.
        UserOperationInvalidState (409): not in CHANGES_REQUESTED.
        UserNotFound (404): revised update_user target is unknown in this tenant.
        IdentifierAlreadyInUse (409): a revised create_user identifier already
            belongs to a live user or another pending create_user proposal.
        AppHTTPException (422): the new payload fails its schema.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != USER_OP_STATUS_CHANGES_REQUESTED:
        raise UserOperationInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise UserOperationForbidden("Only the original maker may revise this request.")

    normalised = _validate_payload(request.operation, payload)
    if request.operation == USER_OP_UPDATE:
        await _assert_target_exists(session, tenant_id, normalised)
    if request.operation == USER_OP_CREATE:
        # revise keeps the request in CHANGES_REQUESTED (no PENDING flip here),
        # and the guard's pending-proposal branch filters status == PENDING, so
        # this very request never collides with itself. No live user has been
        # created yet either, so there is no self identity-row to exclude.
        await _assert_create_identifiers_available(session, tenant_id, normalised)
    request.payload = normalised
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=USER_REVIEW_ROLE_MAKER,
        action=USER_REVIEW_ACTION_REVISED,
    )
    _audit(session, admin, request, "user_op.revised", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def resubmit_user_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Original maker resubmits a CHANGES_REQUESTED request → PENDING.

    A resubmit starts a fresh approval round: any approvals recorded before it no
    longer count (the distinct-approver + N-eyes logic reads only reviews after
    the latest `resubmitted`).

    Raises:
        UserOperationNotFound (404).
        UserOperationForbidden (403): not the original maker.
        UserOperationInvalidState (409): not in CHANGES_REQUESTED.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != USER_OP_STATUS_CHANGES_REQUESTED:
        raise UserOperationInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise UserOperationForbidden("Only the original maker may resubmit this request.")

    request.status = USER_OP_STATUS_PENDING
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=USER_REVIEW_ROLE_MAKER,
        action=USER_REVIEW_ACTION_RESUBMITTED,
    )
    _audit(session, admin, request, "user_op.resubmitted", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def withdraw_user_operation(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserOperationRequest:
    """Original maker abandons a non-terminal request → WITHDRAWN (terminal).

    Raises:
        UserOperationNotFound (404).
        UserOperationForbidden (403): not the original maker.
        UserOperationInvalidState (409): the request is already terminal.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status in USER_OP_TERMINAL_STATUSES:
        raise UserOperationInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise UserOperationForbidden("Only the original maker may withdraw this request.")

    request.status = USER_OP_STATUS_WITHDRAWN
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=USER_REVIEW_ROLE_MAKER,
        action=USER_REVIEW_ACTION_WITHDRAWN,
    )
    _audit(session, admin, request, "user_op.withdrawn", ip_address)
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def list_user_operations(
    session: AsyncSession, tenant_id: UUID, *, status: str | None = None
) -> list[UserOperationRequest]:
    """Return a tenant's user-operation requests, newest-first, optionally by status."""
    stmt = select(UserOperationRequest).where(UserOperationRequest.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(UserOperationRequest.status == status)
    stmt = stmt.order_by(UserOperationRequest.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_user_operation(
    session: AsyncSession, request_id: UUID, tenant_id: UUID
) -> tuple[UserOperationRequest, list[UserOperationReview]]:
    """Return a request with its review thread (oldest-first)."""
    request = await _load_request(session, request_id, tenant_id)
    reviews = await load_reviews(session, request.id)
    return request, reviews
