"""Treasury service — admin view + control of system wallets.

The model:
  - System wallets = `accounts` rows where `user_id IS NULL`.
  - `operator_adjustment` (one per tenant + currency) is the counter-leg
    for admin fund/withdraw on the system float. Its balance tracks net
    external cash that has flowed in/out via bank wires.
  - `fund_user()` reuses the existing `top_up()` service (DEBIT
    system_cash_inflow, CREDIT user_wallet).

Every action below writes an `audit_log` row with the admin's reason.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_admin
from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.payments.service import top_up
from app.modules.treasury.schemas import (
    AdjustSystemWalletResponse,
    FundUserResponse,
    SystemWalletOut,
    SystemWalletTransactionOut,
)
from app.shared.exceptions import (
    AccountNotFound,
    AppHTTPException,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _get_or_create_operator_adjustment(
    session: AsyncSession, *, tenant_id: UUID, currency: str
) -> Account:
    """Fetch-or-create the per-(tenant, currency) operator_adjustment account.

    Lazy so the operator doesn't have to pre-seed anything in a new tenant.
    """
    currency = currency.upper()
    existing = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.currency == currency,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


# -----------------------------------------------------------------------------
# Read endpoints
# -----------------------------------------------------------------------------


async def list_system_wallets(
    session: AsyncSession, *, tenant_id: UUID
) -> list[SystemWalletOut]:
    """Return every system-owned account in the tenant with its live balance."""
    await _assert_tenant_exists(session, tenant_id)
    rows = (
        await session.execute(
            select(Account)
            .where(Account.tenant_id == tenant_id, Account.user_id.is_(None))
            .order_by(Account.account_type, Account.currency)
        )
    ).scalars().all()
    out: list[SystemWalletOut] = []
    for acct in rows:
        balance, _reserved = await derive_balance(session, acct.id)
        out.append(
            SystemWalletOut(
                id=acct.id,
                tenant_id=acct.tenant_id,
                account_type=acct.account_type,
                currency=acct.currency,
                status=acct.status,
                balance=balance,
                created_at=acct.created_at,
            )
        )
    return out


async def list_account_transactions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    limit: int = 50,
) -> list[SystemWalletTransactionOut]:
    """Return recent transactions touching a system account.

    Tenant-scoped — cross-tenant lookups return 404 (no existence leak).
    Joins ledger_entries → transactions so we can surface the entry's
    direction (DEBIT/CREDIT) for the row in the drill-down UI.
    """
    acct = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if acct is None:
        raise AccountNotFound()

    stmt = (
        select(Transaction, LedgerEntry)
        .join(LedgerEntry, LedgerEntry.transaction_id == Transaction.id)
        .where(LedgerEntry.account_id == account_id)
        .order_by(desc(Transaction.created_at))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        SystemWalletTransactionOut(
            transaction_id=txn.id,
            transaction_type=txn.transaction_type,
            status=txn.status,
            entry_type=entry.entry_type,
            entry_amount=Decimal(str(entry.amount)),
            currency=txn.currency,
            created_at=txn.created_at,
        )
        for txn, entry in rows
    ]


# -----------------------------------------------------------------------------
# Mutating endpoints
# -----------------------------------------------------------------------------


async def fund_user(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    amount: Decimal,
    currency: str,
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> FundUserResponse:
    """Admin tops up a user's wallet — wraps the existing `top_up()`.

    Posts the standard balanced transaction (DEBIT system_cash_inflow,
    CREDIT user_wallet) via the same code path the seed uses, then
    writes a `treasury.fund_user` audit row carrying the admin's reason.

    Idempotency-Key here is internally generated — admin actions are
    not naturally idempotent (every "fund again" is a real new top-up).
    """
    await _assert_tenant_exists(session, tenant_id)

    idempotency_key = f"admin-fund-{uuid4().hex}"
    txn = await top_up(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        amount=amount,
        currency=currency,
        idempotency_key=idempotency_key,
    )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.fund_user",
        entity_type="user",
        entity_id=str(user_id),
        after_state={
            "amount": str(amount),
            "currency": currency.upper(),
            "transaction_id": str(txn.id),
            "reason": reason,
        },
        ip_address=ip_address,
    )
    await session.commit()

    # Re-derive the user's wallet balance for the response.
    user_wallet = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == "financial_wallet",
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one()
    new_balance, _ = await derive_balance(session, user_wallet.id)

    return FundUserResponse(
        transaction_id=txn.id,
        user_id=user_id,
        amount=amount,
        currency=currency.upper(),
        new_balance=new_balance,
    )


async def adjust_system_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    amount: Decimal,  # signed
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> AdjustSystemWalletResponse:
    """Fund (positive amount) or withdraw (negative) a system wallet.

    Posts a balanced transaction with the `operator_adjustment` account
    (one per tenant + currency, lazy-created) as the counter-leg.

      amount > 0  (fund the float):
        DEBIT  operator_adjustment   |amount|
        CREDIT target_system_wallet  |amount|

      amount < 0  (withdraw from the float):
        DEBIT  target_system_wallet  |amount|
        CREDIT operator_adjustment   |amount|

    Tenant-scoped — cross-tenant account_id returns 404. The target
    must be a system-owned account (user_id IS NULL). Adjusting a
    user wallet via this surface is rejected (use `fund_user`).

    The operator_adjustment account is itself a valid target — that
    would just be a no-op rebalance, so we reject it as well.
    """
    if amount == 0:
        raise AppHTTPException(
            422, "amount_zero", "Amount must be non-zero."
        )

    await _assert_tenant_exists(session, tenant_id)

    target = (
        await session.execute(
            select(Account).where(
                Account.id == account_id,
                Account.tenant_id == tenant_id,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise AccountNotFound()
    if target.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT:
        raise AppHTTPException(
            422,
            "cannot_adjust_operator_adjustment",
            "operator_adjustment is the counter-leg and cannot itself "
            "be the target of an adjustment.",
        )

    counter = await _get_or_create_operator_adjustment(
        session, tenant_id=tenant_id, currency=target.currency
    )

    magnitude = abs(amount)
    if amount > 0:
        # Fund: float goes up.
        entries = [
            LedgerEntryRequest(
                account_id=counter.id, entry_type="DEBIT", amount=magnitude
            ),
            LedgerEntryRequest(
                account_id=target.id, entry_type="CREDIT", amount=magnitude
            ),
        ]
    else:
        # Withdraw: float goes down.
        entries = [
            LedgerEntryRequest(
                account_id=target.id, entry_type="DEBIT", amount=magnitude
            ),
            LedgerEntryRequest(
                account_id=counter.id, entry_type="CREDIT", amount=magnitude
            ),
        ]

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=f"admin-adjust-{uuid4().hex}",
            transaction_type="treasury.adjust",
            currency=target.currency,
            entries=entries,
            initiated_by=None,
            amount=magnitude,
        ),
    )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.adjust_system_wallet",
        entity_type="account",
        entity_id=str(account_id),
        after_state={
            "amount": str(amount),  # signed in the audit too
            "currency": target.currency,
            "transaction_id": str(txn.id),
            "reason": reason,
            "target_account_type": target.account_type,
        },
        ip_address=ip_address,
    )
    await session.commit()

    new_balance, _ = await derive_balance(session, target.id)
    return AdjustSystemWalletResponse(
        transaction_id=txn.id,
        account_id=target.id,
        amount=amount,
        currency=target.currency,
        new_balance=new_balance,
    )
