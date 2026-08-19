"""Money-operation maker-checker FastAPI router (Epic 18).

Makers (platform-admin) propose / revise / resubmit / withdraw; checkers
(treasury-approver) approve / request-changes. Treasury money-movement endpoints
route through here instead of executing directly. `tenant_id` is an explicit
query param (admins are cross-tenant), matching the config-requests router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
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
    count_money_operations,
    distinct_approver_ids,
    get_money_operation,
    list_money_operations,
    load_reviews,
    load_reviews_for_requests,
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
from app.shared.queue_counts import QueueCountsOut
from app.shared.utils.uuids import parse_uuid

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


async def _account_display_names(
    session: AsyncSession, tenant_id: UUID, account_ids: set[UUID]
) -> dict[UUID, str]:
    """Resolve system-account ids to display names (the `name`, else the
    account_type) in ONE tenant-scoped query. Unknown ids are simply absent."""
    if not account_ids:
        return {}
    result = await session.execute(
        select(Account).where(Account.id.in_(account_ids), Account.tenant_id == tenant_id)
    )
    return {acct.id: acct.name or acct.account_type for acct in result.scalars()}


async def _attach_payload_names(session: AsyncSession, outs: list[MoneyOperationOut]) -> None:
    """Resolve payload subjects to human names so the UI shows people/wallets,
    not raw identifiers/UUIDs.

    - fund_user / withdraw_user → `subject_name` (the funded/withdrawn user).
    - adjust_system_wallet → `account_name` (target) + `bank_mirror_name`.
    - withdraw_user → `bank_mirror_name` (its counter-leg mirror).

    Batched (B7.2): each UNIQUE payload identifier resolves once, all user
    names come from one batch call, and all referenced accounts load in one
    query — page cost does not scale with row count. All outs belong to one
    tenant (both call sites are tenant-scoped endpoints).

    Best-effort: any resolution miss leaves the field None and the UI falls
    back to the raw payload value. Never raises — display enrichment only.
    """
    if not outs:
        return
    tenant_id = outs[0].tenant_id

    # Pass 1 — collect the unique identifiers and account ids across the page.
    identifier_pairs: set[tuple[str, str]] = set()
    account_ids: set[UUID] = set()
    for out in outs:
        payload = out.payload
        if out.operation in (MONEY_OP_FUND_USER, MONEY_OP_WITHDRAW_USER):
            itype = payload.get("identifier_type")
            ivalue = payload.get("identifier_value")
            if itype and ivalue:
                identifier_pairs.add((str(itype), str(ivalue)))
        if out.operation in (MONEY_OP_ADJUST_SYSTEM, MONEY_OP_WITHDRAW_USER):
            mirror_id = parse_uuid(payload.get("bank_mirror_account_id"))
            if mirror_id:
                account_ids.add(mirror_id)
        if out.operation == MONEY_OP_ADJUST_SYSTEM:
            account_id = parse_uuid(payload.get("account_id"))
            if account_id:
                account_ids.add(account_id)

    # Resolve once per unique identifier (a page funding one user many times
    # costs one lookup), then every user name in one batch.
    user_id_by_pair: dict[tuple[str, str], UUID] = {}
    for itype, ivalue in identifier_pairs:
        try:
            ident = await resolve_identifier(
                session,
                tenant_id,
                itype,  # type: ignore[arg-type]
                ivalue,
            )
            user_id_by_pair[(itype, ivalue)] = ident.user_id
        except AppHTTPException:
            # Unknown/unresolvable identifier — leave subject_name None.
            pass
    user_names = await resolve_user_names(
        session, tenant_id=tenant_id, user_ids=user_id_by_pair.values()
    )
    account_names = await _account_display_names(session, tenant_id, account_ids)

    # Pass 2 — assign from the maps.
    for out in outs:
        payload = out.payload
        if out.operation in (MONEY_OP_FUND_USER, MONEY_OP_WITHDRAW_USER):
            pair = (str(payload.get("identifier_type")), str(payload.get("identifier_value")))
            user_id = user_id_by_pair.get(pair)
            out.subject_name = user_names.get(user_id) if user_id else None
        if out.operation in (MONEY_OP_ADJUST_SYSTEM, MONEY_OP_WITHDRAW_USER):
            mirror_id = parse_uuid(payload.get("bank_mirror_account_id"))
            out.bank_mirror_name = account_names.get(mirror_id) if mirror_id else None
        if out.operation == MONEY_OP_ADJUST_SYSTEM:
            account_id = parse_uuid(payload.get("account_id"))
            out.account_name = account_names.get(account_id) if account_id else None


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
    q: str | None = Query(None, max_length=200),
    limit: int | None = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[MoneyOperationOut]:
    """List a tenant's money operations, optionally filtered by status,
    searched by q (whole-queue free text — B7.2c), and windowed by limit/offset
    (B7.1 — the approvals page fetches a bounded window, never the whole
    queue)."""
    _ = admin
    requests = await list_money_operations(
        session, tenant_id, status=status_filter, q=q, limit=limit, offset=offset
    )
    # One batched query for every review thread on the page (B7.2 — never one
    # query per row).
    reviews_by_request = await load_reviews_for_requests(session, [r.id for r in requests])
    outs = [_build_out(r, reviews_by_request.get(r.id, [])) for r in requests]
    await _attach_admin_names(session, outs)
    await _attach_payload_names(session, outs)
    return outs


@router.get("/counts", response_model=QueueCountsOut)
async def get_counts(
    tenant_id: UUID,
    q: str | None = Query(None, max_length=200),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> QueueCountsOut:
    """Per-status counts for the approvals tab bar — one grouped query, no rows.
    `q` scopes the counts to search matches (B7.2c).

    This STATIC route is declared before `GET /{request_id}` so "counts" is
    never captured as a request id.
    """
    _ = admin
    return await count_money_operations(session, tenant_id, q=q)


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
    # Same display enrichment as the list endpoint — the detail drawer refetches
    # through here, so skipping it would regress names back to raw UUIDs.
    await _attach_payload_names(session, [out])
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
