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
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_admin
from app.modules.identity.schemas import IdentifierType
from app.modules.identity.service import resolve_identifier
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
    WithdrawFromUserResponse,
)
from app.shared.exceptions import (
    AccountNotFound,
    AppHTTPException,
    InsufficientFunds,
    NothingToWithdraw,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
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


async def resolve_user_financial_wallet(
    session: AsyncSession,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
    currency: str,
) -> tuple[UUID, Account]:
    """Resolve a user by identifier and return (user_id, their financial_wallet).

    Shared by the operator and external fund/withdraw paths. It can NEVER return
    a system wallet — system accounts have `user_id IS NULL`, so filtering by the
    resolved `user_id` guarantees a user-owned wallet. This is precisely why
    fund / withdraw / withdraw_all can never touch a system wallet.

    Raises:
        UserNotFound: identifier doesn't resolve in this tenant.
        AccountNotFound: the user has no financial_wallet for `currency`.
    """
    identifier_row = await resolve_identifier(
        session, tenant_id, cast(IdentifierType, identifier_type), identifier_value
    )
    user_id = identifier_row.user_id
    wallet = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one_or_none()
    if wallet is None:
        raise AccountNotFound()
    return user_id, wallet


async def resolve_withdraw_amount(
    session: AsyncSession,
    wallet: Account,
    *,
    amount: Decimal | None,
    withdraw_all: bool,
) -> Decimal:
    """Return the amount to withdraw, enforcing overdraft before any write.

    `withdraw_all` resolves to the wallet's full available balance
    (balance - reserved); otherwise the requested `amount`.

    Raises:
        NothingToWithdraw: withdraw_all but available <= 0.
        InsufficientFunds: requested amount > available.
    """
    balance, reserved = await derive_balance(session, wallet.id)
    available = balance - reserved
    if withdraw_all:
        if available <= Decimal("0"):
            raise NothingToWithdraw()
        return available
    # The request schema guarantees a positive amount when withdraw_all is False.
    assert amount is not None
    if available < amount:
        raise InsufficientFunds()
    return amount


async def post_user_withdraw(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    wallet: Account,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
) -> Transaction:
    """Post the balanced withdraw legs: DEBIT the user wallet, CREDIT the
    operator_adjustment system account (transaction_type='withdraw').

    The caller owns the audit row + the surrounding commit; this only appends
    the ledger transaction (which commits internally via `post_transaction`).
    """
    operator_adjustment = await _get_or_create_operator_adjustment(
        session, tenant_id=tenant_id, currency=currency
    )
    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="withdraw",
            currency=currency,
            amount=amount,
            initiated_by=user_id,
            entries=[
                LedgerEntryRequest(account_id=wallet.id, entry_type="DEBIT", amount=amount),
                LedgerEntryRequest(
                    account_id=operator_adjustment.id, entry_type="CREDIT", amount=amount
                ),
            ],
        ),
    )


# -----------------------------------------------------------------------------
# Read endpoints
# -----------------------------------------------------------------------------


async def list_system_wallets(session: AsyncSession, *, tenant_id: UUID) -> list[SystemWalletOut]:
    """Return every system-owned account in the tenant with its live balance."""
    await _assert_tenant_exists(session, tenant_id)
    rows = (
        (
            await session.execute(
                select(Account)
                .where(Account.tenant_id == tenant_id, Account.user_id.is_(None))
                .order_by(Account.account_type, Account.currency)
            )
        )
        .scalars()
        .all()
    )
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
    identifier_type: str,
    identifier_value: str,
    amount: Decimal,
    currency: str,
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> FundUserResponse:
    """Admin tops up a user's wallet — wraps the existing `top_up()`.

    The user is resolved from their registered identifier (phone, email,
    account_number, card_number) — operators don't have UUIDs at the
    counter. Posts the standard balanced transaction (DEBIT
    system_cash_inflow, CREDIT user_wallet) and writes a
    `treasury.fund_user` audit row with the admin's reason.

    Idempotency-Key here is internally generated — admin actions are
    not naturally idempotent (every "fund again" is a real new top-up).

    Raises:
        TenantNotFound: tenant_id is unknown.
        UserNotFound: identifier doesn't resolve in this tenant.
    """
    await _assert_tenant_exists(session, tenant_id)
    identifier_row = await resolve_identifier(
        session, tenant_id, cast(IdentifierType, identifier_type), identifier_value
    )
    user_id = identifier_row.user_id

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
            "identifier_type": identifier_type,
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


async def withdraw_from_user(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
    amount: Decimal | None,
    currency: str,
    reason: str,
    admin: AdminPrincipal,
    ip_address: str | None = None,
    withdraw_all: bool = False,
) -> WithdrawFromUserResponse:
    """Admin debits a user's wallet and returns the funds to the operator pool.

    The mirror of `fund_user`: DEBIT user's financial_wallet, CREDIT the
    `operator_adjustment` system account. Both are real money moving back
    into the operator's cash float at the counter.

    Admin operations are PIN-less and fee-less: the operator's Keycloak
    session is the only authentication. The target user is identified
    by a registered identifier, not a UUID.

    Args:
        tenant_id: Tenant scope.
        identifier_type / identifier_value: Resolved to a user via
            identity.resolve_identifier — typically phone at the counter.
        amount, currency: Withdraw parameters.
        reason: Free-text reason, persisted in the audit row.
        admin: Authenticated admin initiating the action.
        ip_address: Caller IP for the audit row.

    Returns:
        WithdrawFromUserResponse with the new wallet balance.

    Raises:
        TenantNotFound: tenant_id is unknown.
        UserNotFound: identifier doesn't resolve in this tenant.
        AccountNotFound: user has no financial_wallet for this currency.
        InsufficientFunds: user balance < requested amount.

    Side effects:
        Posts a balanced 2-leg transaction (transaction_type='withdraw').
        Writes a `treasury.withdraw_from_user` audit row with the reason.
        Commits the session.
    """
    await _assert_tenant_exists(session, tenant_id)
    currency = currency.upper()
    user_id, user_wallet = await resolve_user_financial_wallet(
        session, tenant_id, identifier_type, identifier_value, currency
    )
    final_amount = await resolve_withdraw_amount(
        session, user_wallet, amount=amount, withdraw_all=withdraw_all
    )
    txn = await post_user_withdraw(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        wallet=user_wallet,
        amount=final_amount,
        currency=currency,
        idempotency_key=f"admin-withdraw-{uuid4().hex}",
    )

    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="treasury.withdraw_from_user",
        entity_type="user",
        entity_id=str(user_id),
        after_state={
            "amount": str(final_amount),
            "currency": currency,
            "transaction_id": str(txn.id),
            "reason": reason,
            "identifier_type": identifier_type,
            "withdraw_all": withdraw_all,
        },
        ip_address=ip_address,
    )
    await session.commit()

    new_balance, _ = await derive_balance(session, user_wallet.id)
    return WithdrawFromUserResponse(
        transaction_id=txn.id,
        user_id=user_id,
        amount=final_amount,
        currency=currency,
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
        raise AppHTTPException(422, "amount_zero", "Amount must be non-zero.")

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
            LedgerEntryRequest(account_id=counter.id, entry_type="DEBIT", amount=magnitude),
            LedgerEntryRequest(account_id=target.id, entry_type="CREDIT", amount=magnitude),
        ]
    else:
        # Withdraw: float goes down.
        entries = [
            LedgerEntryRequest(account_id=target.id, entry_type="DEBIT", amount=magnitude),
            LedgerEntryRequest(account_id=counter.id, entry_type="CREDIT", amount=magnitude),
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
