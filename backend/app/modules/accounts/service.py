"""Accounts service — account lifecycle and balance derivation.

Balance is computed from `ledger_entries` (the source of truth) — the
`account_balance_snapshots` table is a future read optimisation, not used
in Phase A.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.schemas import CreateAccountRequest
from app.shared.exceptions import (
    AccountNotFound,
    InvalidAccountType,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPES,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    Account,
    LedgerEntry,
    Tenant,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject creates against unknown tenants."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def create_account(
    session: AsyncSession, request: CreateAccountRequest
) -> Account:
    """Create a new account.

    Validates that:
      - tenant_id is known
      - account_type is one of the allowed values (also enforced by DB CHECK)
      - currency is uppercase 3-letter ISO 4217

    Args:
        session: Async DB session.
        request: Validated CreateAccountRequest.

    Returns:
        The persisted Account.

    Raises:
        TenantNotFound: 404 when tenant_id is unknown.
        InvalidAccountType: 422 when account_type is unrecognised (belt-and-braces
            on top of the Pydantic Literal).
    """
    if request.account_type not in ACCOUNT_TYPES:
        raise InvalidAccountType()

    await _assert_tenant_exists(session, request.tenant_id)

    account = Account(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        merchant_id=request.merchant_id,
        account_type=request.account_type,
        currency=request.currency.upper(),
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def get_account(
    session: AsyncSession, account_id: UUID, tenant_id: UUID
) -> Account:
    """Fetch an account, enforcing tenant isolation.

    Cross-tenant lookups MUST return 404, never the data (NFR-0220).

    Args:
        session: Async DB session.
        account_id: The account UUID to fetch.
        tenant_id: The caller's tenant scope.

    Returns:
        The Account if it exists in this tenant.

    Raises:
        AccountNotFound: 404 if no match (also when the account exists in a
            different tenant — we do NOT leak existence).
    """
    result = await session.execute(
        select(Account).where(
            Account.id == account_id, Account.tenant_id == tenant_id
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFound()
    return account


async def derive_balance(
    session: AsyncSession, account_id: UUID
) -> tuple[Decimal, Decimal]:
    """Compute (balance, reserved_balance) from ledger entries.

    Per the ledger invariants:
      - balance        = SUM(CREDIT where status=COMPLETED) - SUM(DEBIT where status=COMPLETED)
      - reserved       = SUM(DEBIT where status=PENDING) - SUM(CREDIT where status=PENDING)

    Reserved is the value held against in-progress transactions
    (Pay-PRD-0210, Pay-PRD-0220). `available = balance - reserved`.

    Args:
        session: Async DB session.
        account_id: The account whose balance to compute.

    Returns:
        Tuple of (balance, reserved_balance), both as Decimal.
    """
    completed_balance = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount),
                        else_=-LedgerEntry.amount,
                    )
                ),
                0,
            )
        ).where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
    )
    balance = Decimal(completed_balance.scalar_one() or 0)

    pending_reserved = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == ENTRY_DEBIT, LedgerEntry.amount),
                        else_=-LedgerEntry.amount,
                    )
                ),
                0,
            )
        ).where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.status == ENTRY_STATUS_PENDING,
        )
    )
    reserved = Decimal(pending_reserved.scalar_one() or 0)
    # Reserved should never be negative for a healthy account, but the
    # subtraction in the SQL handles credits-pending edge cases consistently.

    return balance, reserved
