"""Accounts module FastAPI router (Phase F.4 — admin-gated).

Both endpoints expose tenant-wide account data — only admins should see
balances for arbitrary accounts. End-users see their own balance via the
catalog `/me/summary` endpoint, not this router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.accounts.schemas import (
    AccountOut,
    BalanceResponse,
    CreateAccountRequest,
)
from app.modules.accounts.service import (
    create_account,
    derive_balance,
    get_account,
)

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut, status_code=201)
async def post_account(
    request: CreateAccountRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> AccountOut:
    """Create a new account (Pay-PRD-0110).

    Admin-only. End-user accounts are created automatically when a user is
    registered (Phase F.2 OTP flow); this endpoint exists for system /
    master / provider wallet management.
    """
    _ = admin  # F.5 will use admin.id for audit_log writes
    account = await create_account(session, request)
    return AccountOut.model_validate(account)


@router.get("/{account_id}/balance", response_model=BalanceResponse)
async def get_balance(
    account_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> BalanceResponse:
    """Return derived balance for an account (Pay-PRD-0130, Pay-PRD-0140).

    Admin-only — exposes any account's balance in the tenant. End-users
    fetch their own balance via `/api/v1/catalog/me/summary`.
    """
    _ = admin
    account = await get_account(session, account_id, tenant_id)
    balance, reserved = await derive_balance(session, account.id)
    return BalanceResponse(
        account_id=account.id,
        balance=balance,
        reserved_balance=reserved,
        available_balance=balance - reserved,
        currency=account.currency,
    )
