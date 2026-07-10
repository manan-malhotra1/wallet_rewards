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
    InsufficientFunds,
    MaxBalanceExceeded,
    RecipientMaxBalanceExceeded,
    UnbalancedTransaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
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
        is_reversal: When True the balance guard skips the max_balance ceiling on
            credit legs — a reversal / refund restores funds and must never be
            blocked by a cap (invariant #11). Overdraft on debit legs still applies.
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
    is_reversal: bool = False


async def post_transaction(session: AsyncSession, request: PostTransactionRequest) -> Transaction:
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
    accounts = await _load_and_assert_accounts(session, request)

    # Idempotency check FIRST — return existing transaction if any.
    existing = await _find_by_idempotency(session, request.tenant_id, request.idempotency_key)
    if existing is not None:
        return existing

    # Balance guard (invariant #11): lock every user-wallet leg and enforce
    # overdraft + max_balance UNDER that lock, held continuously through the
    # commit below. Balance is SUM(ledger_entries), so this row lock is the only
    # thing that serialises concurrent writers — the single authoritative place
    # these limits are enforced, so every current and future money path inherits
    # it just by posting here.
    await _enforce_balance_guard(session, request, accounts)

    entry_status = (
        ENTRY_STATUS_COMPLETED if request.status == TXN_STATUS_COMPLETED else ENTRY_STATUS_PENDING
    )

    headline_amount = (
        request.amount if request.amount is not None else max(e.amount for e in request.entries)
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
        existing = await _find_by_idempotency(session, request.tenant_id, request.idempotency_key)
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


async def _load_and_assert_accounts(
    session: AsyncSession, request: PostTransactionRequest
) -> dict[UUID, Account]:
    """Load every referenced account (tenant-scoped) and assert all exist.

    Returns a ``{account_id: Account}`` map so the balance guard can classify
    each wallet leg (type, owner, currency) without a second query.

    Raises:
        AccountNotFound: a referenced account is missing from this tenant.
    """
    account_ids = {e.account_id for e in request.entries}
    result = await session.execute(
        select(Account).where(
            Account.id.in_(account_ids),
            Account.tenant_id == request.tenant_id,
        )
    )
    accounts = {account.id: account for account in result.scalars().all()}
    if set(accounts) != account_ids:
        raise AccountNotFound()
    return accounts


async def _enforce_balance_guard(
    session: AsyncSession,
    request: PostTransactionRequest,
    accounts: dict[UUID, Account],
) -> None:
    """Lock every user-wallet leg and enforce overdraft + max_balance under it.

    Balance is ``SUM(ledger_entries)``, so no single row self-serialises
    concurrent writers; a check-then-write on the derived balance races two
    transactions past a cap or into overdraft. This is the single choke point
    (invariant #11) where a ``FOR UPDATE`` lock gates that check:

      * net debit  -> reject (InsufficientFunds) if it would overdraw available.
      * net credit -> reject (MaxBalanceExceeded) if it would breach max_balance,
        UNLESS ``is_reversal`` — a refund restores funds and may never be blocked.

    Only ``financial_wallet`` accounts carry these semantics; system, merchant
    *collection* (e.g. ``airtime_merchant_holding``) and points accounts have no
    cap and are skipped untouched.

    Locks are taken in account-id order and BEFORE any balance read, so two
    multi-wallet transactions (e.g. p2p, which locks both legs) can never
    deadlock on inverse lock orders. Each lock is held until the commit inside
    ``post_transaction`` — never across an external call (NFR-0130).

    Raises:
        InsufficientFunds (409): a debit would overdraw a wallet.
        MaxBalanceExceeded (409): a credit would breach the owner's ceiling.
        RecipientMaxBalanceExceeded (409): ditto, but the initiator is a different
            user (p2p) — detail-free so the recipient's balance never leaks.
    """
    # Local imports avoid an import cycle (accounts/limits both sit above ledger).
    from app.modules.accounts.service import derive_balance, lock_account_for_update
    from app.modules.limits.service import resolve_max_balance

    # Net movement per touched account (CREDIT +, DEBIT -). One account may appear
    # in several legs (e.g. principal + fee debit), so accumulate before checking.
    deltas: dict[UUID, Decimal] = {}
    for entry in request.entries:
        signed = entry.amount if entry.entry_type == ENTRY_CREDIT else -entry.amount
        deltas[entry.account_id] = deltas.get(entry.account_id, Decimal(0)) + signed

    guarded = sorted(
        account_id
        for account_id, delta in deltas.items()
        if delta != 0 and accounts[account_id].account_type == ACCOUNT_TYPE_FINANCIAL_WALLET
    )
    if not guarded:
        return

    # Acquire ALL locks (id order) before ANY balance read — inverse-order locking
    # of two wallets is the only way concurrent transactions could deadlock here.
    for account_id in guarded:
        await lock_account_for_update(session, account_id)

    for account_id in guarded:
        account = accounts[account_id]
        delta = deltas[account_id]
        balance, reserved = await derive_balance(session, account_id)
        if delta < 0:
            # Overdraft: available (balance - reserved) must absorb the net debit.
            if balance - reserved + delta < 0:
                raise InsufficientFunds()
        elif not request.is_reversal and account.user_id is not None:
            # A financial_wallet always has an owner; resolve their type to find
            # the cap. The explicit None check also narrows the type for mypy.
            cap = await resolve_max_balance(
                session,
                tenant_id=request.tenant_id,
                user_id=account.user_id,
                currency=account.currency,
            )
            if cap is not None and balance + delta > cap:
                # Opaque recipient error when some OTHER user drove the credit
                # (p2p); the owner's own specific cap otherwise (self / system fund).
                if request.initiated_by is not None and account.user_id != request.initiated_by:
                    raise RecipientMaxBalanceExceeded()
                raise MaxBalanceExceeded(str(cap))


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


async def sum_completed_balance(session: AsyncSession, account_id: UUID) -> Decimal:
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
