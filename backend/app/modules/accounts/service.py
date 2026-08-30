"""Accounts service — account lifecycle and balance derivation.

Balance is computed from `ledger_entries` (the source of truth) — the
`account_balance_snapshots` table is a future read optimisation, not used
in Phase A.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.modules.accounts.schemas import CreateAccountRequest
from app.modules.audit.service import record_audit_for_admin
from app.modules.ledger.snapshots import read_snapshot, sum_from_ledger
from app.shared.exceptions import (
    AccountAlreadyExists,
    AccountNotFound,
    InvalidAccountType,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPES,
    Account,
    Tenant,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject creates against unknown tenants."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def create_account(
    session: AsyncSession,
    request: CreateAccountRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Account:
    """Create a new account.

    Validates that:
      - tenant_id is known
      - account_type is one of the allowed values (also enforced by DB CHECK)
      - currency is uppercase 3-letter ISO 4217

    Args:
        session: Async DB session.
        request: Validated CreateAccountRequest.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP (audit context).

    Returns:
        The persisted Account.

    Raises:
        TenantNotFound: 404 when tenant_id is unknown.
        InvalidAccountType: 422 when account_type is unrecognised (belt-and-braces
            on top of the Pydantic Literal).

    Side effects:
        Writes an `account.created` audit_log row (owner scope + type/currency,
        never secrets), committed atomically with the insert (NFR-0250).
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
    try:
        await session.flush()
    except IntegrityError as exc:
        # Partial UNIQUE index `uq_accounts_user_scoped` (or
        # `uq_accounts_system_scoped`) fires when the same (tenant, user,
        # type, currency) tuple is recreated. Surface as 409 so callers
        # (admin UI, load scripts) can treat it as idempotent.
        await session.rollback()
        if "uq_accounts_user_scoped" in str(exc.orig).lower() or (
            "uq_accounts_system_scoped" in str(exc.orig).lower()
        ):
            raise AccountAlreadyExists() from exc
        raise
    record_audit_for_admin(
        session,
        admin,
        tenant_id=request.tenant_id,
        action="account.created",
        entity_type="account",
        entity_id=str(account.id),
        after_state={
            "account_type": account.account_type,
            "currency": account.currency,
            "user_id": str(account.user_id) if account.user_id else None,
            "merchant_id": str(account.merchant_id) if account.merchant_id else None,
        },
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(account)
    return account


async def get_account(session: AsyncSession, account_id: UUID, tenant_id: UUID) -> Account:
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
        select(Account).where(Account.id == account_id, Account.tenant_id == tenant_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFound()
    return account


async def derive_balance(session: AsyncSession, account_id: UUID) -> tuple[Decimal, Decimal]:
    """Return (balance, reserved_balance) for an account.

    Per the ledger invariants:
      - balance        = SUM(CREDIT where status=COMPLETED) - SUM(DEBIT where status=COMPLETED)
      - reserved       = SUM(DEBIT where status=PENDING) - SUM(CREDIT where status=PENDING)

    Reserved is the value held against in-progress transactions
    (Pay-PRD-0210, Pay-PRD-0220). `available = balance - reserved`.

    Served from the `account_balance_snapshots` cache, which every ledger write
    updates in its own transaction (see `ledger/snapshots.py`). That keeps this
    O(1): the aggregate it replaced grew with an account's whole history and ran
    while holding the account write lock, so on a shared account it got slower
    forever — 931ms by 5M entries, and the tenant fee wallet takes an entry from
    every single transaction.

    Falls back to deriving from the ledger when an account has no snapshot row
    yet — an account created before the backfill, or one never touched — and
    seeds the row so the next read is cheap. The ledger stays the source of
    truth; this only decides how the answer is obtained.

    Args:
        session: Async DB session.
        account_id: The account whose balance to read.

    Returns:
        Tuple of (balance, reserved_balance), both as Decimal.
    """
    cached = await read_snapshot(session, account_id)
    if cached is not None:
        return cached
    # No row yet (an account created before the backfill). Derive and return it
    # WITHOUT writing: this is a read path, and a read that writes a value it
    # computed moments earlier can land after a concurrent writer and discard
    # their update — which is how a cached balance drifts from the ledger and a
    # money guard reads a stale figure. The row gets created correctly by the
    # next `apply_deltas`, which runs post-flush inside the write's transaction.
    return await sum_from_ledger(session, account_id)


async def lock_account_for_update(session: AsyncSession, account_id: UUID) -> None:
    """Acquire a row-level write lock (SELECT ... FOR UPDATE) on an account.

    The shared double-spend guard for every balance-bearing money move
    (Pay-PRD-0220). Two concurrent debits that each read the pre-move balance
    and both write would drive the balance negative; the lock forces the second
    caller to wait until the first commits, so it sees the post-move balance and
    its overdraft / limit check correctly fails.

    Args:
        session: Async DB session.
        account_id: The balance-bearing account to lock.

    Side effects / caller contract:
        The lock is held until the surrounding transaction commits or rolls
        back. Acquire it BEFORE reading the balance, and ensure NO intervening
        ``commit()`` runs between the lock and the money-leg write — a mid-flow
        commit (e.g. lazy system-account creation) releases the lock and reopens
        the race (Epic 18 S4 H-01). Pre-create any lazily-built counter accounts
        before calling this.
    """
    await session.execute(select(Account.id).where(Account.id == account_id).with_for_update())
