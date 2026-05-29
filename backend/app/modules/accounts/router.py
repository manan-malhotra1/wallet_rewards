"""Accounts module FastAPI router (Phase A test-only endpoints)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
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

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts (test-only)"])


@router.post("", response_model=AccountOut, status_code=201)
async def post_account(
    request: CreateAccountRequest,
    session: AsyncSession = Depends(get_async_session),
) -> AccountOut:
    """Create a new account (Pay-PRD-0110).

    Test-only — no auth in Phase A. Phase 2 gates this behind admin role.
    """
    account = await create_account(session, request)
    return AccountOut.model_validate(account)


@router.get("/{account_id}/balance", response_model=BalanceResponse)
async def get_balance(
    account_id: UUID,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> BalanceResponse:
    """Return derived balance for an account (Pay-PRD-0130, Pay-PRD-0140)."""
    account = await get_account(session, account_id, tenant_id)
    balance, reserved = await derive_balance(session, account.id)
    return BalanceResponse(
        account_id=account.id,
        balance=balance,
        reserved_balance=reserved,
        available_balance=balance - reserved,
        currency=account.currency,
    )
