"""Money-operation maker-checker FastAPI router (Epic 18).

Makers (platform-admin) propose / revise / resubmit / withdraw; checkers
(treasury-approver) approve / request-changes. Treasury money-movement endpoints
route through here instead of executing directly. `tenant_id` is an explicit
query param (admins are cross-tenant), matching the config-requests router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.admin_profiles import resolve_admin_names
from app.modules.identity.service import resolve_identifier, resolve_user_names
from app.modules.money_operations.schemas import (
    MoneyOperationCommentRequest,
    MoneyOperationOut,
    MoneyOperationProposeRequest,
    MoneyOperationReviseRequest,
    MoneyReviewOut,
)
from app.modules.money_operations.service import (
    approve_money_operation,
    distinct_approver_ids,
    get_money_operation,
    list_money_operations,
    load_reviews,
    propose_money_operation,
    request_money_op_changes,
    resubmit_money_operation,
    revise_money_operation,
    withdraw_money_operation,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    MONEY_OP_ADJUST_SYSTEM,
    MONEY_OP_FUND_USER,
    MONEY_OP_WITHDRAW_USER,
    Account,
    MoneyOperationRequest,
    MoneyOperationReview,
)

router = APIRouter(prefix="/api/v1/money-operations", tags=["money-operations"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


def _build_out(
    request: MoneyOperationRequest, reviews: list[MoneyOperationReview]
) -> MoneyOperationOut:
    """Assemble a MoneyOperationOut with review thread + N-eyes progress."""
    out = MoneyOperationOut.model_validate(request)
    out.reviews = [MoneyReviewOut.model_validate(r) for r in reviews]
    out.approvals_count = len(distinct_approver_ids(reviews))
    return out


async def _attach_admin_names(session: AsyncSession, outs: list[MoneyOperationOut]) -> None:
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


async def _account_display_name(
    session: AsyncSession, tenant_id: UUID, account_id: object
) -> str | None:
    """Resolve a system-account id to its display name (its `name`, else the
    account_type). Tenant-scoped, best-effort — None when the id is bad/absent."""
    try:
        acct = await session.get(Account, UUID(str(account_id)))
    except (ValueError, TypeError):
        return None
    if acct is None or acct.tenant_id != tenant_id:
        return None
    return acct.name or acct.account_type


async def _attach_payload_names(session: AsyncSession, outs: list[MoneyOperationOut]) -> None:
    """Resolve payload subjects to human names so the UI shows people/wallets,
    not raw identifiers/UUIDs.

    - fund_user / withdraw_user → `subject_name` (the funded/withdrawn user).
    - adjust_system_wallet → `account_name` (target) + `bank_mirror_name`.
    - withdraw_user → `bank_mirror_name` (its counter-leg mirror).

    Best-effort: any resolution miss leaves the field None and the UI falls
    back to the raw payload value. Never raises — display enrichment only.
    """
    for out in outs:
        payload = out.payload
        if out.operation in (MONEY_OP_FUND_USER, MONEY_OP_WITHDRAW_USER):
            itype = payload.get("identifier_type")
            ivalue = payload.get("identifier_value")
            if itype and ivalue:
                try:
                    ident = await resolve_identifier(
                        session,
                        out.tenant_id,
                        itype,  # type: ignore[arg-type]
                        str(ivalue),
                    )
                    names = await resolve_user_names(
                        session, tenant_id=out.tenant_id, user_ids=[ident.user_id]
                    )
                    out.subject_name = names.get(ident.user_id)
                except AppHTTPException:
                    # Unknown/unresolvable identifier — leave subject_name None.
                    pass
        if out.operation in (MONEY_OP_ADJUST_SYSTEM, MONEY_OP_WITHDRAW_USER):
            mirror_id = payload.get("bank_mirror_account_id")
            if mirror_id:
                out.bank_mirror_name = await _account_display_name(
                    session, out.tenant_id, mirror_id
                )
        if out.operation == MONEY_OP_ADJUST_SYSTEM:
            account_id = payload.get("account_id")
            if account_id:
                out.account_name = await _account_display_name(session, out.tenant_id, account_id)


async def serialize_money_operation(
    session: AsyncSession, request: MoneyOperationRequest
) -> MoneyOperationOut:
    """Load a single request's reviews, build its OUT, attach admin names.

    Shared with the treasury router, whose money-movement endpoints now return
    the pending money-operation request they propose.
    """
    reviews = await load_reviews(session, request.id)
    out = _build_out(request, reviews)
    await _attach_admin_names(session, [out])
    await _attach_payload_names(session, [out])
    return out


@router.post("", response_model=MoneyOperationOut, status_code=201)
async def post_propose(
    body: MoneyOperationProposeRequest,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Maker proposes a money operation → PENDING (nothing executes yet)."""
    result = await propose_money_operation(
        session,
        operation=body.operation,
        payload=body.payload,
        tenant_id=tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


@router.get("", response_model=list[MoneyOperationOut])
async def get_operations(
    tenant_id: UUID,
    status_filter: str | None = None,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[MoneyOperationOut]:
    """List a tenant's money operations (optionally filtered by status)."""
    _ = admin
    requests = await list_money_operations(session, tenant_id, status=status_filter)
    outs: list[MoneyOperationOut] = []
    for request in requests:
        reviews = await load_reviews(session, request.id)
        outs.append(_build_out(request, reviews))
    await _attach_admin_names(session, outs)
    await _attach_payload_names(session, outs)
    return outs


@router.get("/{request_id}", response_model=MoneyOperationOut)
async def get_operation(
    request_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Fetch one money operation with its full review thread + progress."""
    _ = admin
    request, reviews = await get_money_operation(session, request_id, tenant_id)
    out = _build_out(request, reviews)
    await _attach_admin_names(session, [out])
    return out


@router.post("/{request_id}/approve", response_model=MoneyOperationOut)
async def post_approve(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("treasury-approver")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Checker approves; applies once N distinct approvals are reached."""
    result = await approve_money_operation(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await serialize_money_operation(session, result)


@router.post("/{request_id}/request-changes", response_model=MoneyOperationOut)
async def post_request_changes(
    request_id: UUID,
    tenant_id: UUID,
    body: MoneyOperationCommentRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("treasury-approver")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Checker requests changes (mandatory comment) → CHANGES_REQUESTED."""
    result = await request_money_op_changes(
        session,
        request_id,
        tenant_id,
        admin=admin,
        comment=body.comment,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


@router.patch("/{request_id}", response_model=MoneyOperationOut)
async def patch_revise(
    request_id: UUID,
    tenant_id: UUID,
    body: MoneyOperationReviseRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Original maker edits a CHANGES_REQUESTED request's payload in place."""
    result = await revise_money_operation(
        session,
        request_id,
        tenant_id,
        admin=admin,
        payload=body.payload,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


@router.post("/{request_id}/resubmit", response_model=MoneyOperationOut)
async def post_resubmit(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Original maker resubmits a CHANGES_REQUESTED request → PENDING (fresh round)."""
    result = await resubmit_money_operation(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await serialize_money_operation(session, result)


@router.post("/{request_id}/withdraw", response_model=MoneyOperationOut)
async def post_withdraw(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """Original maker abandons a non-terminal request → WITHDRAWN."""
    result = await withdraw_money_operation(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await serialize_money_operation(session, result)
