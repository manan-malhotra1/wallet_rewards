"""Treasury FastAPI router (admin-gated).

Routes:
  - GET   /system-wallets                     list system accounts + balances
  - GET   /system-wallets/{id}/transactions    drill-down (paginated)
  - POST  /fund-user                          PROPOSE an admin fund
  - POST  /withdraw                           PROPOSE an admin pull-back
  - POST  /adjust-system-wallet               PROPOSE a system-wallet adjust
  - POST  /bank-mirrors                       PROPOSE a new bank mirror
  - PATCH /bank-mirrors/{account_id}          rename a bank mirror (direct)

Epic 18 — the four money-MOVING endpoints (fund-user, withdraw,
adjust-system-wallet, bank-mirrors POST) no longer execute directly: each now
PROPOSES a money-operation and returns the pending request, which executes only
after N-eyes maker-checker approval. `rename_bank_mirror` moves no money and
stays a direct operation.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.money_operations import propose_money_operation, serialize_money_operation
from app.modules.money_operations.schemas import MoneyOperationOut
from app.modules.treasury.schemas import (
    AdjustSystemWalletRequest,
    CreateBankMirrorRequest,
    FundUserRequest,
    RenameBankMirrorRequest,
    SystemWalletOut,
    SystemWalletTransactionOut,
    WithdrawFromUserRequest,
)
from app.modules.treasury.service import (
    list_account_transactions,
    list_system_wallets,
    project_system_wallet,
    rename_bank_mirror,
)
from app.shared.models import (
    MONEY_OP_ADJUST_SYSTEM,
    MONEY_OP_CREATE_BANK_MIRROR,
    MONEY_OP_FUND_USER,
    MONEY_OP_WITHDRAW_USER,
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
    offset: int = Query(default=0, ge=0),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[SystemWalletTransactionOut]:
    """Paginated recent transactions touching the account (limit/offset window)."""
    _ = admin
    return await list_account_transactions(
        session, tenant_id=tenant_id, account_id=account_id, limit=limit, offset=offset
    )


@router.post("/fund-user", response_model=MoneyOperationOut, status_code=201)
async def post_fund_user(
    request: FundUserRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """PROPOSE an admin fund (Epic 18) — executes only after N-eyes approval.

    User is identified by a registered identifier (phone, email, account or
    card). Returns the pending money-operation request; the fund posts (debit
    system_cash_inflow, credit the user's wallet) when a distinct checker
    approves.
    """
    result = await propose_money_operation(
        session,
        operation=MONEY_OP_FUND_USER,
        payload={
            "identifier_type": request.identifier_type,
            "identifier_value": request.identifier_value,
            "amount": request.amount,
            "currency": request.currency,
            "reason": request.reason,
        },
        tenant_id=request.tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


@router.post("/withdraw", response_model=MoneyOperationOut, status_code=201)
async def post_withdraw_from_user(
    request: WithdrawFromUserRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """PROPOSE an admin pull-back (Epic 18) — executes only after N-eyes approval.

    User identified by phone / email / account / card — same shape as fund.
    Returns the pending money-operation request; the withdraw posts (debit the
    user wallet, credit the chosen bank mirror) when a distinct checker approves.
    """
    result = await propose_money_operation(
        session,
        operation=MONEY_OP_WITHDRAW_USER,
        payload={
            "identifier_type": request.identifier_type,
            "identifier_value": request.identifier_value,
            "amount": request.amount,
            "withdraw_all": request.withdraw_all,
            "currency": request.currency,
            "bank_mirror_account_id": request.bank_mirror_account_id,
            "reason": request.reason,
        },
        tenant_id=request.tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


@router.post(
    "/adjust-system-wallet",
    response_model=MoneyOperationOut,
    status_code=201,
)
async def post_adjust_system_wallet(
    request: AdjustSystemWalletRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """PROPOSE a system-wallet adjust (Epic 18) — executes only after approval.

    Signed amount: positive funds the wallet, negative withdraws; the chosen
    bank mirror is the counter-leg. Returns the pending money-operation request.
    """
    result = await propose_money_operation(
        session,
        operation=MONEY_OP_ADJUST_SYSTEM,
        payload={
            "account_id": request.account_id,
            "amount": request.amount,
            "bank_mirror_account_id": request.bank_mirror_account_id,
            "reason": request.reason,
        },
        tenant_id=request.tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


@router.post("/bank-mirrors", response_model=MoneyOperationOut, status_code=201)
async def post_create_bank_mirror(
    request: CreateBankMirrorRequest,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MoneyOperationOut:
    """PROPOSE a new named bank mirror (Epic 18) — created only after approval.

    Returns the pending money-operation request; the operator_adjustment account
    is created when a distinct checker approves.
    """
    result = await propose_money_operation(
        session,
        operation=MONEY_OP_CREATE_BANK_MIRROR,
        payload={"currency": request.currency, "name": request.name},
        tenant_id=tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return await serialize_money_operation(session, result)


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
