"""Payments service — P2P orchestration and internal top-up.

The full PRD orchestration sequence (Pay-PRD-0260) is:
    1. Role check
    2. Limits check
    3. Pricing calculation
    4. Ledger write

Phase B implements step 4 only. Steps 1–3 are explicitly TODO with the relevant
PRD references. The architecture supports plugging them in without changing the
caller — they belong inside this service, before the `post_transaction` call.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.identity.service import resolve_identifier
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.payments.schemas import IdentifierType
from app.modules.roles.service import require_permission
from app.shared.exceptions import (
    AccountNotFound,
    CurrencyMismatch,
    InsufficientFunds,
    SelfTransferNotAllowed,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    Transaction,
    User,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_user_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    currency: str,
) -> Account:
    """Return the user's `financial_wallet` for the given currency, or 404.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: User whose wallet we want.
        currency: 3-letter ISO 4217 (case-insensitive).

    Returns:
        The matching Account row.

    Raises:
        AccountNotFound: 404 when no matching wallet exists in this tenant.
    """
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.currency == currency.upper(),
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFound()
    return account


async def _lock_account_for_update(
    session: AsyncSession, account_id: UUID
) -> None:
    """Acquire a row-level write lock on the account.

    Prevents the classic double-spend race: two concurrent P2P transfers from
    the same wallet that each see the full balance and both write debits.
    The lock holds until the surrounding DB transaction commits.
    """
    await session.execute(
        select(Account.id).where(Account.id == account_id).with_for_update()
    )


async def p2p_transfer(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sender_user_id: UUID,
    recipient_identifier_type: IdentifierType,
    recipient_identifier_value: str,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
) -> tuple[Transaction, UUID]:
    """Execute a peer-to-peer transfer between two users in the same tenant.

    Steps (matches PRD Pay-PRD-0260 ordering):
      1. Validate tenant exists.
      2. Resolve recipient identifier -> user_id (tenant-scoped).
      3. Reject self-transfer.
      4. Find sender + recipient wallets in the requested currency.
      5. Lock sender wallet for the duration of the DB transaction.
      6. Overdraft check (Pay-PRD-0220) — reject BEFORE any ledger write.
      7. Post balanced transaction via the ledger service.

    Steps 1.5 (role), 2.5 (limits), 3.5 (pricing) — TODO, Phase C+.

    Args:
        session: Async DB session (commits inside `post_transaction`).
        tenant_id: Tenant scope.
        sender_user_id: User initiating the transfer.
        recipient_identifier_type: Identifier kind used to find the recipient.
        recipient_identifier_value: Raw identifier value.
        amount: Positive Decimal amount.
        currency: 3-letter ISO 4217 (case-insensitive).
        idempotency_key: Client-supplied unique key (Pay-PRD-0200). Replays of
            the same key return the original transaction.

    Returns:
        (Transaction, recipient_user_id).

    Raises:
        TenantNotFound: unknown tenant.
        UserNotFound: recipient identifier not registered in this tenant.
        SelfTransferNotAllowed: sender == recipient.
        AccountNotFound: sender or recipient lacks a wallet in this currency.
        CurrencyMismatch: defence-in-depth — request currency mismatches an
            account's currency (the wallet lookup already filters, so this
            normally can't fire, but the check is here for future-proofing).
        InsufficientFunds: sender's available balance < amount.
    """
    await _assert_tenant_exists(session, tenant_id)

    # 1. Role check (Pay-PRD-0260 step 1, Pay-PRD-0440/0450/0460).
    # Sender must hold an active role permitting "p2p". Fails BEFORE any
    # further work — no lock acquired, no ledger touched.
    await require_permission(session, sender_user_id, "p2p")

    # 2. Resolve recipient identifier (tenant-scoped — Pay-PRD-0060).
    recipient_id_row = await resolve_identifier(
        session,
        tenant_id,
        recipient_identifier_type,
        recipient_identifier_value,
    )
    recipient_user_id = recipient_id_row.user_id

    # 3. Self-transfer guard.
    if sender_user_id == recipient_user_id:
        raise SelfTransferNotAllowed()

    # 4. Wallet lookups (also enforces tenant isolation — both wallets must
    # exist in this tenant in this currency).
    sender_wallet = await _find_user_wallet(
        session,
        tenant_id=tenant_id,
        user_id=sender_user_id,
        currency=currency,
    )
    recipient_wallet = await _find_user_wallet(
        session,
        tenant_id=tenant_id,
        user_id=recipient_user_id,
        currency=currency,
    )

    # Defence-in-depth: the wallet query already filters by currency, but a
    # future code change might relax that. Re-check here.
    if sender_wallet.currency != recipient_wallet.currency:
        raise CurrencyMismatch()

    # 5. Lock sender wallet to serialise concurrent same-sender transfers.
    await _lock_account_for_update(session, sender_wallet.id)

    # 6. Overdraft prevention (Pay-PRD-0220) — must happen BEFORE the ledger write.
    balance, reserved = await derive_balance(session, sender_wallet.id)
    available = balance - reserved
    if available < amount:
        raise InsufficientFunds()

    # 7. Post the balanced transaction. The ledger service handles idempotency,
    # double-entry validation, and the COMMIT.
    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="p2p",
            currency=currency.upper(),
            entries=[
                LedgerEntryRequest(
                    account_id=sender_wallet.id,
                    entry_type=ENTRY_DEBIT,
                    amount=amount,
                ),
                LedgerEntryRequest(
                    account_id=recipient_wallet.id,
                    entry_type=ENTRY_CREDIT,
                    amount=amount,
                ),
            ],
            initiated_by=sender_user_id,
            amount=amount,
        ),
    )

    return txn, recipient_user_id


async def _get_or_create_system_cash_inflow(
    session: AsyncSession, tenant_id: UUID, currency: str
) -> Account:
    """Idempotent fetch-or-create for the per-(tenant, currency) cash inflow account.

    Used by `top_up()` so the seed and future top-up endpoint don't need to
    pre-create the account out-of-band.
    """
    currency = currency.upper()
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
            Account.currency == currency,
            Account.user_id.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if account is not None:
        return account
    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency=currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def top_up(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
) -> Transaction:
    """Internal top-up — credit a user's wallet from outside the system.

    Posts a balanced transaction:
      DEBIT  system_cash_inflow (created lazily if missing)
      CREDIT user's financial_wallet in the requested currency

    NOT exposed via HTTP in Phase B — the seed and future Pay-PRD-0320
    endpoint will call this. Exposing it as an admin API endpoint comes later
    once auth + role checks are in place.

    Args:
        session: Async DB session.
        tenant_id, user_id, amount, currency, idempotency_key: as P2P.

    Returns:
        The posted Transaction.

    Raises:
        TenantNotFound, AccountNotFound: same semantics as P2P.
    """
    await _assert_tenant_exists(session, tenant_id)

    user_wallet = await _find_user_wallet(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency
    )
    inflow = await _get_or_create_system_cash_inflow(session, tenant_id, currency)

    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="top_up",
            currency=currency.upper(),
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id,
                    entry_type=ENTRY_DEBIT,
                    amount=amount,
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id,
                    entry_type=ENTRY_CREDIT,
                    amount=amount,
                ),
            ],
            initiated_by=None,  # system-initiated
            amount=amount,
        ),
    )


# Bind User to the import graph so it doesn't trigger import warnings —
# `User` is referenced in this module's docstrings.
_ = User
