"""Treasury FastAPI router (admin-gated).

Four routes:
  - GET  /system-wallets                     list system accounts + balances
  - GET  /system-wallets/{id}/transactions    drill-down (paginated)
  - POST /fund-user                          admin top-up wrapper
  - POST /adjust-system-wallet               fund/withdraw via operator_adjustment
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
    FundUserRequest,
    FundUserResponse,
    SystemWalletOut,
    SystemWalletTransactionOut,
)
from app.modules.treasury.service import (
    adjust_system_wallet,
    fund_user,
    list_account_transactions,
    list_system_wallets,
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


@router.post(
    "/fund-user", response_model=FundUserResponse, status_code=201
)
async def post_fund_user(
    request: FundUserRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> FundUserResponse:
    """Admin top-up — debits system_cash_inflow, credits the user's wallet."""
    return await fund_user(
        session,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        amount=request.amount,
        currency=request.currency,
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
        reason=request.reason,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
