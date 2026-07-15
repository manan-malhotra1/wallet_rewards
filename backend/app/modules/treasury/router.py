"""Treasury FastAPI router (admin-gated).

Routes:
  - GET   /system-wallets                     list system accounts + balances
  - GET   /system-wallets/{id}/transactions    drill-down (paginated)
  - POST  /fund-user                          admin fund wrapper
  - POST  /withdraw                           admin pull-back wrapper
  - POST  /adjust-system-wallet               fund/withdraw via a bank mirror
  - POST  /bank-mirrors                       create a named bank mirror
  - PATCH /bank-mirrors/{account_id}          rename a bank mirror
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.treasury.schemas import (
    AdjustSystemWalletRequest,
    AdjustSystemWalletResponse,
    CreateBankMirrorRequest,
    FundUserRequest,
    FundUserResponse,
    RenameBankMirrorRequest,
    SystemWalletOut,
    SystemWalletTransactionOut,
    WithdrawFromUserRequest,
    WithdrawFromUserResponse,
)
from app.modules.treasury.service import (
    adjust_system_wallet,
    create_bank_mirror,
    fund_user,
    list_account_transactions,
    list_system_wallets,
    project_system_wallet,
    rename_bank_mirror,
    withdraw_from_user,
)

router = APIRouter(prefix="/api/v1/treasury", tags=["treasury"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


@router.get("/system-wallets", response_model=list[SystemWalletOut])
async def get_system_wallets(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[SystemWalletOut]:
    """List every system-owned account in the tenant with derived balance."""
    _ = admin
    return await list_system_wallets(session, tenant_id=tenant_id)


@router.get(
    "/system-wallets/{account_id}/transactions",
    response_model=list[SystemWalletTransactionOut],
)
async def get_system_wallet_transactions(
    account_id: UUID,
    tenant_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[SystemWalletTransactionOut]:
    """Paginated recent transactions touching the account."""
    _ = admin
    return await list_account_transactions(
        session, tenant_id=tenant_id, account_id=account_id, limit=limit
    )


@router.post("/fund-user", response_model=FundUserResponse, status_code=201)
async def post_fund_user(
    request: FundUserRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> FundUserResponse:
    """Admin fund — debits system_cash_inflow, credits the user's wallet.

    User is identified by a registered identifier (phone, email, account
    or card) — operators never type a UUID.
    """
    return await fund_user(
        session,
        tenant_id=request.tenant_id,
        identifier_type=request.identifier_type,
        identifier_value=request.identifier_value,
        amount=request.amount,
        currency=request.currency,
        reason=request.reason,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )


@router.post("/withdraw", response_model=WithdrawFromUserResponse, status_code=201)
async def post_withdraw_from_user(
    request: WithdrawFromUserRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> WithdrawFromUserResponse:
    """Admin pull-back — debits the user wallet, credits operator_adjustment.

    User identified by phone / email / account / card — same shape as
    Fund. PIN-less and fee-less.
    """
    return await withdraw_from_user(
        session,
        tenant_id=request.tenant_id,
        identifier_type=request.identifier_type,
        identifier_value=request.identifier_value,
        amount=request.amount,
        withdraw_all=request.withdraw_all,
        currency=request.currency,
        bank_mirror_account_id=request.bank_mirror_account_id,
        reason=request.reason,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )


@router.post(
    "/adjust-system-wallet",
    response_model=AdjustSystemWalletResponse,
    status_code=201,
)
async def post_adjust_system_wallet(
    request: AdjustSystemWalletRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> AdjustSystemWalletResponse:
    """Fund (positive amount) or withdraw (negative) a system wallet.

    Uses `operator_adjustment` as the counter-leg so the ledger stays
    double-entry balanced. Requires a non-empty `reason` for audit.
    """
    return await adjust_system_wallet(
        session,
        tenant_id=request.tenant_id,
        account_id=request.account_id,
        amount=request.amount,
        bank_mirror_account_id=request.bank_mirror_account_id,
        reason=request.reason,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )


@router.post("/bank-mirrors", response_model=SystemWalletOut, status_code=201)
async def post_create_bank_mirror(
    request: CreateBankMirrorRequest,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SystemWalletOut:
    """Create a new named bank mirror (operator_adjustment) for a currency."""
    account = await create_bank_mirror(
        session,
        tenant_id=tenant_id,
        currency=request.currency,
        name=request.name,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await project_system_wallet(session, account)


@router.patch("/bank-mirrors/{account_id}", response_model=SystemWalletOut)
async def patch_rename_bank_mirror(
    account_id: UUID,
    request: RenameBankMirrorRequest,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SystemWalletOut:
    """Rename an existing bank mirror."""
    account = await rename_bank_mirror(
        session,
        account_id=account_id,
        tenant_id=tenant_id,
        name=request.name,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await project_system_wallet(session, account)
