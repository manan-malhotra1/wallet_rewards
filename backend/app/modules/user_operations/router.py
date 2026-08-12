"""User-operation maker-checker FastAPI router (admin create/edit user).

Makers (platform-admin) propose / revise / resubmit / withdraw; checkers
(user-approver) approve / request-changes. This is the ADMIN maker-checker path
for creating and editing users — the direct `POST /identity/users` endpoint is
unchanged and remains the partner / external / test path. `tenant_id` is an
explicit query param (admins are cross-tenant), matching the money-operations
router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.admin_profiles import resolve_admin_names
from app.modules.identity.service import resolve_user_names
from app.modules.user_operations.schemas import (
    UserOperationCommentRequest,
    UserOperationOut,
    UserOperationProposeRequest,
    UserOperationReviseRequest,
    UserReviewOut,
)
from app.modules.user_operations.service import (
    approve_user_operation,
    distinct_approver_ids,
    get_user_operation,
    list_user_operations,
    load_reviews,
    propose_user_operation,
    request_user_op_changes,
    resubmit_user_operation,
    revise_user_operation,
    withdraw_user_operation,
)
from app.shared.models import (
    USER_OP_UPDATE,
    UserOperationRequest,
    UserOperationReview,
)

router = APIRouter(prefix="/api/v1/user-operations", tags=["user-operations"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


def _build_out(
    request: UserOperationRequest, reviews: list[UserOperationReview]
) -> UserOperationOut:
    """Assemble a UserOperationOut with review thread + N-eyes progress."""
    out = UserOperationOut.model_validate(request)
    out.reviews = [UserReviewOut.model_validate(r) for r in reviews]
    out.approvals_count = len(distinct_approver_ids(reviews))
    return out


async def _attach_admin_names(session: AsyncSession, outs: list[UserOperationOut]) -> None:
    """Resolve maker/reviewer subs → display names on the OUT objects.

    So the UI renders human names, never bare IDs. Unresolved subs stay None.
    """
    subs: set[str] = set()
    for out in outs:
        subs.add(out.maker_admin_id)
        subs.update(r.actor_admin_id for r in out.reviews)
    names = await resolve_admin_names(session, subs)
    for out in outs:
        out.maker_admin_name = names.get(out.maker_admin_id)
        for review in out.reviews:
            review.actor_admin_name = names.get(review.actor_admin_id)


async def _attach_target_names(session: AsyncSession, outs: list[UserOperationOut]) -> None:
    """For update_user requests, resolve the edited user's current display name.

    So the UI shows who's being edited rather than a bare UUID. Best-effort: an
    unresolvable / missing target leaves `target_name` None.
    """
    for out in outs:
        if out.operation != USER_OP_UPDATE:
            continue
        raw = out.payload.get("target_user_id")
        if not raw:
            continue
        try:
            target_id = UUID(str(raw))
        except (ValueError, TypeError):
            continue
        names = await resolve_user_names(session, tenant_id=out.tenant_id, user_ids=[target_id])
        out.target_name = names.get(target_id)


async def _serialize(session: AsyncSession, request: UserOperationRequest) -> UserOperationOut:
    """Load a single request's reviews, build its OUT, attach names."""
    reviews = await load_reviews(session, request.id)
    out = _build_out(request, reviews)
    await _attach_admin_names(session, [out])
    await _attach_target_names(session, [out])
    return out


@router.post("", response_model=UserOperationOut, status_code=201)
async def post_propose(
    body: UserOperationProposeRequest,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Maker proposes a user operation → PENDING (nothing applies yet)."""
    result = await propose_user_operation(
        session,
        operation=body.operation,
        payload=body.payload,
        tenant_id=tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await _serialize(session, result)


@router.get("", response_model=list[UserOperationOut])
async def get_operations(
    tenant_id: UUID,
    status_filter: str | None = None,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[UserOperationOut]:
    """List a tenant's user operations (optionally filtered by status)."""
    _ = admin
    requests = await list_user_operations(session, tenant_id, status=status_filter)
    outs: list[UserOperationOut] = []
    for request in requests:
        reviews = await load_reviews(session, request.id)
        outs.append(_build_out(request, reviews))
    await _attach_admin_names(session, outs)
    await _attach_target_names(session, outs)
    return outs


@router.get("/{request_id}", response_model=UserOperationOut)
async def get_operation(
    request_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Fetch one user operation with its full review thread + progress."""
    _ = admin
    request, reviews = await get_user_operation(session, request_id, tenant_id)
    out = _build_out(request, reviews)
    await _attach_admin_names(session, [out])
    await _attach_target_names(session, [out])
    return out


@router.post("/{request_id}/approve", response_model=UserOperationOut)
async def post_approve(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("user-approver")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Checker approves; applies once N distinct approvals are reached."""
    result = await approve_user_operation(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _serialize(session, result)


@router.post("/{request_id}/request-changes", response_model=UserOperationOut)
async def post_request_changes(
    request_id: UUID,
    tenant_id: UUID,
    body: UserOperationCommentRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("user-approver")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Checker requests changes (mandatory comment) → CHANGES_REQUESTED."""
    result = await request_user_op_changes(
        session,
        request_id,
        tenant_id,
        admin=admin,
        comment=body.comment,
        ip_address=_client_ip(fastapi_request),
    )
    return await _serialize(session, result)


@router.patch("/{request_id}", response_model=UserOperationOut)
async def patch_revise(
    request_id: UUID,
    tenant_id: UUID,
    body: UserOperationReviseRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Original maker edits a CHANGES_REQUESTED request's payload in place."""
    result = await revise_user_operation(
        session,
        request_id,
        tenant_id,
        admin=admin,
        payload=body.payload,
        ip_address=_client_ip(fastapi_request),
    )
    return await _serialize(session, result)


@router.post("/{request_id}/resubmit", response_model=UserOperationOut)
async def post_resubmit(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Original maker resubmits a CHANGES_REQUESTED request → PENDING (fresh round)."""
    result = await resubmit_user_operation(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _serialize(session, result)


@router.post("/{request_id}/withdraw", response_model=UserOperationOut)
async def post_withdraw(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOperationOut:
    """Original maker abandons a non-terminal request → WITHDRAWN."""
    result = await withdraw_user_operation(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _serialize(session, result)
