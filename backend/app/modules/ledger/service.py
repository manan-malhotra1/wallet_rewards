"""Ledger service — atomic double-entry posting.

Every state-mutating ledger write goes through `post_transaction` so the
following invariants are enforced in one place:

  - At least one DEBIT and one CREDIT entry per transaction (Pay-PRD-0180).
  - Sum of CREDIT - SUM of DEBIT = 0 across the entries (NFR-0100).
  - Idempotency: `(tenant_id, idempotency_key)` is unique (Pay-PRD-0200).
  - Entries are immutable: callers MAY NOT mutate returned LedgerEntry rows.

External callers (payments, rewards, redemption) build a list of entries
and pass it here. They handle their own external-API calls AFTER this
function commits — never inside (NFR-0130).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exceptions import (
    AccountNotFound,
    DuplicateIdempotencyKey,
    UnbalancedTransaction,
)
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    TXN_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Transaction,
)


@dataclass(frozen=True)
class LedgerEntryRequest:
    """One side of a double-entry transaction.

    Attributes:
        account_id: The account to debit or credit.
        entry_type: 'DEBIT' or 'CREDIT'.
        amount: Positive Decimal. Validation is done by `post_transaction`.
    """

    account_id: UUID
    entry_type: str
    amount: Decimal


@dataclass(frozen=True)
class PostTransactionRequest:
    """Input to `post_transaction`.

    Attributes:
        tenant_id: Tenant scope; cross-checked against the resolved accounts.
        idempotency_key: Unique per tenant. Duplicate keys return the
            existing transaction (Pay-PRD-0200).
        transaction_type: Short string tag (e.g. 'p2p', 'reward_issuance').
        currency: 3-letter ISO 4217. Must match every entry's account currency.
        entries: At least 2 entries, balanced to zero.
        initiated_by: Optional user_id; NULL for system-initiated.
        amount: The transaction's headline amount (typically equal to the
            largest single entry). Stored for fast filtering and display.
        fee_amount: Service charge applied on top of `amount`, already
            represented in `entries` as a sender→system_fee_collected leg.
            Persisted on the transaction row so the fee is displayable
            without re-deriving it from the ledger (Pay-PRD-0260).
        status: Initial status. Defaults to COMPLETED for synchronous flows;
            payments orchestrator passes PENDING for flows that need external calls.
    """

    tenant_id: UUID
    idempotency_key: str
    transaction_type: str
    currency: str
    entries: list[LedgerEntryRequest]
    initiated_by: UUID | None = None
    amount: Decimal | None = None
    fee_amount: Decimal = Decimal("0")
    status: str = TXN_STATUS_COMPLETED


async def post_transaction(
    session: AsyncSession, request: PostTransactionRequest
) -> Transaction:
    """Append a balanced double-entry transaction atomically.

    On success the transaction and all entries are committed in a single DB
    transaction. The function returns the Transaction with its `entries`
    available via the relationship (lazy-loaded — caller may need a refresh).

    Idempotency: if a transaction with the same `(tenant_id, idempotency_key)`
    already exists, that existing transaction is returned WITHOUT writing new
    rows. Callers should not rely on the new entries matching the original
    request — the original wins.

    Args:
        session: Async DB session (NOT pre-committed by caller).
        request: PostTransactionRequest with balanced entries.

    Returns:
        The persisted (or already-existing) Transaction.

    Raises:
        UnbalancedTransaction: 422 when entries don't sum to zero or fewer
            than 2 entries are provided.
        AccountNotFound: 404 when any referenced account doesn't exist in
            the tenant.
        DuplicateIdempotencyKey: 409 when the key is reused on the rare race
            where two different bodies share the same key.
    """
    _assert_balanced(request)
    await _assert_accounts_belong_to_tenant(session, request)

    # Idempotency check FIRST — return existing transaction if any.
    existing = await _find_by_idempotency(
        session, request.tenant_id, request.idempotency_key
    )
    if existing is not None:
        return existing

    entry_status = (
        ENTRY_STATUS_COMPLETED
        if request.status == TXN_STATUS_COMPLETED
        else ENTRY_STATUS_PENDING
    )

    headline_amount = (
        request.amount
        if request.amount is not None
        else max(e.amount for e in request.entries)
    )

    txn = Transaction(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        transaction_type=request.transaction_type,
        status=request.status,
        initiated_by=request.initiated_by,
        amount=headline_amount,
        fee_amount=request.fee_amount,
        currency=request.currency.upper(),
    )
    session.add(txn)
    await session.flush()  # populate txn.id

    for entry in request.entries:
        session.add(
            LedgerEntry(
                transaction_id=txn.id,
                account_id=entry.account_id,
                entry_type=entry.entry_type,
                amount=entry.amount,
                currency=request.currency.upper(),
                status=entry_status,
            )
        )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # The most likely cause is a concurrent insert that won the unique
        # constraint race. Re-check; if a row exists, return it.
        existing = await _find_by_idempotency(
            session, request.tenant_id, request.idempotency_key
        )
        if existing is not None:
            return existing
        # Otherwise this is a genuine conflict — surface as 409.
        raise DuplicateIdempotencyKey() from exc

    await session.refresh(txn)
    return txn


def _assert_balanced(request: PostTransactionRequest) -> None:
    """Reject a transaction whose entries don't sum to zero (NFR-0100)."""
    if len(request.entries) < 2:
        raise UnbalancedTransaction()

    credits = sum(
        (e.amount for e in request.entries if e.entry_type == ENTRY_CREDIT),
        start=Decimal(0),
    )
    debits = sum(
        (e.amount for e in request.entries if e.entry_type == ENTRY_DEBIT),
        start=Decimal(0),
    )
    if credits != debits:
        raise UnbalancedTransaction()
    if credits == 0:
        # All-zero amounts are useless and disallowed by the DB CHECK anyway.
        raise UnbalancedTransaction()


async def _assert_accounts_belong_to_tenant(
    session: AsyncSession, request: PostTransactionRequest
) -> None:
    """Ensure every referenced account exists in the request's tenant."""
    account_ids = {e.account_id for e in request.entries}
    result = await session.execute(
        select(Account.id).where(
            Account.id.in_(account_ids),
            Account.tenant_id == request.tenant_id,
        )
    )
    found = {row[0] for row in result.all()}
    if found != account_ids:
        raise AccountNotFound()


async def _find_by_idempotency(
    session: AsyncSession, tenant_id: UUID, key: str
) -> Transaction | None:
    """Fetch an existing transaction by (tenant_id, idempotency_key) or None."""
    result = await session.execute(
        select(Transaction).where(
            Transaction.tenant_id == tenant_id,
            Transaction.idempotency_key == key,
        )
    )
    return result.scalar_one_or_none()


async def sum_completed_balance(
    session: AsyncSession, account_id: UUID
) -> Decimal:
    """Convenience: SUM(CREDIT) - SUM(DEBIT) over COMPLETED entries.

    Use this for places that don't need the full (balance, reserved) tuple
    that `accounts.derive_balance` returns.

    Args:
        session: Async DB session.
        account_id: The account to sum.

    Returns:
        Net Decimal balance.
    """
    result = await session.execute(
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
    return Decimal(result.scalar_one() or 0)
