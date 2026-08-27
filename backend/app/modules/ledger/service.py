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
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, case, func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exceptions import (
    AccountNotFound,
    DuplicateIdempotencyKey,
    InsufficientCashbackFunds,
    InsufficientCommissionBalance,
    InsufficientFloat,
    InsufficientFunds,
    MaxBalanceExceeded,
    RecipientMaxBalanceExceeded,
    UnbalancedTransaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_CASHBACK_PROVIDER,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    TXN_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Transaction,
)

# Account types whose net DEBIT is gated by the overdraft floor under the
# FOR UPDATE lock (invariant #11). `financial_wallet` is the user wallet;
# `system_cash_inflow` is the operator cash float, which must be pre-funded from
# the bank and may NOT go negative (no float overdraft). Both are locked and
# serialised at this choke point. Only `financial_wallet` additionally carries
# the max_balance CEILING (the float has no user_id, so the credit branch below
# skips it). Other system / pool accounts (operator_adjustment bank mirrors,
# merchant collection, points) are unguarded — no floor, no cap. The
# `cashback_provider_wallet` (Pay-PRD-1230) joins the floor: it funds internal
# redemption payouts + cashback rewards and must be pre-funded via treasury —
# a debit that would overdraw it raises the distinct InsufficientCashbackFunds.
_OVERDRAFT_GUARDED_ACCOUNT_TYPES = frozenset(
    {
        ACCOUNT_TYPE_FINANCIAL_WALLET,
        ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        ACCOUNT_TYPE_CASHBACK_PROVIDER,
        ACCOUNT_TYPE_COMMISSION_WALLET,
    }
)

# --- Guard axis 2: the max_balance CEILING ---------------------------------
# Account types whose net CREDIT is gated by the owner's max_balance.
#
# This set is deliberately EXPLICIT rather than derived from
# `account.user_id is not None`. That derivation was correct only while
# `financial_wallet` was the sole user-owned guarded type. `commission_wallet`
# is user-owned AND uncapped (spec 2026-08-26 D5: an agent may accrue any
# amount of commission), so ownership no longer implies a ceiling. Deriving the
# ceiling from ownership here would silently cap commission accrual — a bug no
# commission test would catch, because it only fires once an agent's accrual
# crosses their configured max_balance in production.
_CEILING_GUARDED_ACCOUNT_TYPES = frozenset({ACCOUNT_TYPE_FINANCIAL_WALLET})


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
class RewardTrigger:
    """Set by money services when a transaction should drive reward evaluation.

    Its presence (plus tenant business_type == 'both') makes `post_transaction`
    write a `reward_outbox` row atomically with the ledger commit. Reward-issuance
    calls leave it None so reward payouts never loop back into the evaluator.

    Modelled as a frozen dataclass to match `LedgerEntryRequest` /
    `PostTransactionRequest` — this is an internal service request object, not an
    HTTP API schema, so it stays consistent with the ledger module's existing
    dataclass style rather than introducing a Pydantic model here.

    Attributes:
        user_id: The user the transaction (and any resulting reward) belongs to.
        transaction_type: The rewardable type tag (must be in REWARDABLE_TYPES to
            actually enqueue — enforced as defence-in-depth in post_transaction).
        amount: Headline transaction amount the reward rules evaluate against.
        currency: 3-letter ISO 4217 of `amount`.
        merchant_id: Optional merchant the transaction was with (segment rules).
    """

    user_id: UUID
    transaction_type: str
    amount: Decimal
    currency: str
    merchant_id: UUID | None = None


@dataclass(frozen=True)
class PostTransactionRequest:
    """Input to `post_transaction`.

    Attributes:
        tenant_id: Tenant scope; cross-checked against the resolved accounts.
        idempotency_key: Unique per tenant. Duplicate keys return the
            existing transaction (Pay-PRD-0200).
        transaction_type: Short string tag (e.g. 'p2p', 'reward_issuance').
        currency: 3-letter ISO 4217. Must match every entry's account currency.
        base_transaction_type: The BASE flow this transaction belongs to.
            Omitted → defaults to `transaction_type`, which is correct for
            every base-service flow; a derived service passes its base so
            clients can group by flow without knowing every derived code
            (spec §12.1).
        entries: At least 2 entries, balanced to zero.
        initiated_by: Optional user_id; NULL for system-initiated.
        amount: The transaction's headline amount (typically equal to the
            largest single entry). Stored for fast filtering and display.
        fee_amount: Service charge applied on top of `amount`, already
            represented in `entries` as a sender→system_fee_collected leg.
            Persisted on the transaction row so the fee is displayable
            without re-deriving it from the ledger (Pay-PRD-0260).
        parent_commission_amount: Commission paid to the earner's PARENT
            (spec 2026-08-26), already represented in `entries` as a second
            commission_pool -> parent leg. Display-only on the transaction row.
        commission_amount: Commission paid to the acting agent (Pricing v2),
            already represented in `entries` as a commission_pool→agent leg.
            Display-only on the transaction row.
        tax_amount: Total tax collected (on fee + commission), already
            represented in `entries` as taxes-wallet credit legs. Display-only.
        status: Initial status. Defaults to COMPLETED for synchronous flows;
            payments orchestrator passes PENDING for flows that need external calls.
        is_reversal: When True the balance guard skips the max_balance ceiling on
            credit legs — a reversal / refund restores funds and must never be
            blocked by a cap (invariant #11). Overdraft on debit legs still applies.
        skip_receive_cap: When True the balance guard skips the max_balance
            ceiling on credit legs (like `is_reversal`) but the transaction is
            NOT a reversal — used for earned payouts such as an agent commission
            credit, which must not be blocked by the agent's own cap (Story 20.3).
            Overdraft on debit legs still applies.
        reward_trigger: Set by money services when this wallet transaction should
            drive reward evaluation. When present AND the tenant is in `both` mode
            AND the type is rewardable, `post_transaction` writes a `reward_outbox`
            row in the SAME DB transaction as the ledger commit. Reward-issuance
            calls leave it None so payouts never loop back into the evaluator.
    """

    tenant_id: UUID
    idempotency_key: str
    transaction_type: str
    currency: str
    entries: list[LedgerEntryRequest]
    initiated_by: UUID | None = None
    amount: Decimal | None = None
    base_transaction_type: str | None = None
    fee_amount: Decimal = Decimal("0")
    commission_amount: Decimal = Decimal("0")
    parent_commission_amount: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    status: str = TXN_STATUS_COMPLETED
    is_reversal: bool = False
    skip_receive_cap: bool = False
    reward_trigger: RewardTrigger | None = None


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
        request: PostTransactionRequest with balanced entries. Its
            `base_transaction_type`, when omitted, defaults to
            `transaction_type` so every existing caller is unaffected.

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

    # Customer-facing reference for a genuinely NEW transaction only — an
    # idempotent replay returned above and MUST NOT consume a sequence number
    # or change the stored reference. One `now(UTC)` feeds the timestamp part;
    # the running number comes from this tenant's Postgres sequence.
    created_at = datetime.now(UTC)
    seq = await _next_reference_number(session, request.tenant_id)
    reference = build_reference(created_at, seq)

    txn = Transaction(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        reference=reference,
        transaction_type=request.transaction_type,
        base_transaction_type=request.base_transaction_type or request.transaction_type,
        status=request.status,
        initiated_by=request.initiated_by,
        amount=headline_amount,
        fee_amount=request.fee_amount,
        commission_amount=request.commission_amount,
        parent_commission_amount=request.parent_commission_amount,
        tax_amount=request.tax_amount,
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

    # Internal wallet → rewards trigger (spec 2026-08-03). Written atomically
    # with the ledger commit so the intent can never be lost. Gated to `both`
    # tenants; only money services pass reward_trigger, so reward issuance
    # itself never loops. Defense-in-depth: enforce the rewardable allowlist.
    # txn.id is already populated by the flush() above (entries FK it), so no
    # extra flush is needed for outbox.transaction_id.
    if request.reward_trigger is not None:
        from app.shared.models.rewards import REWARDABLE_TYPES, RewardOutbox
        from app.shared.tenant_mode import rewards_from_wallet_enabled

        rt = request.reward_trigger
        # ELIGIBILITY is a property of the BASE flow ("is this kind of movement
        # rewardable at all?"), while rule TARGETING uses the resolved code that
        # `rt.transaction_type` carries — so a derived service needs its own rule
        # (spec §8). Gating on the resolved code instead would make derived
        # services permanently unrewardable no matter how they are configured,
        # because REWARDABLE_TYPES only ever lists platform base codes.
        base_type = request.base_transaction_type or request.transaction_type
        if base_type in REWARDABLE_TYPES and await rewards_from_wallet_enabled(
            session, request.tenant_id
        ):
            session.add(
                RewardOutbox(
                    tenant_id=request.tenant_id,
                    user_id=rt.user_id,
                    transaction_id=txn.id,
                    transaction_type=rt.transaction_type,
                    amount=rt.amount,
                    currency=rt.currency,
                    merchant_id=rt.merchant_id,
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


def _needs_lock(
    account: Account, delta: Decimal, *, is_reversal: bool, skip_receive_cap: bool
) -> bool:
    """Will a guard actually FIRE on this account? Lock it only if so (B15).

    The lock used to be taken for any non-zero delta on a guarded type, credits
    included. But the checks below are asymmetric: the floor applies only to a
    net DEBIT, and the ceiling only to `financial_wallet`. A credit into an
    uncapped guarded wallet — a commission wallet, the float, the cashback
    wallet — therefore took a `FOR UPDATE` row lock held through commit and was
    then checked against nothing.

    That was not merely wasted work, because of WHOSE row it is. Parent
    commission credits the same super-agent's commission wallet on every
    cash-in and cash-out their downline performs, so an entire downline
    serialised on one row — contention scaling with the shape of the hierarchy
    rather than the transaction rate.

    Dropping those locks cannot breach a floor. A credit only ever INCREASES a
    balance, so a concurrent debit that reads without seeing an uncommitted
    credit sees LESS than the truth and errs toward rejecting — conservative,
    never permissive. Two credits racing on a CAPPED wallet still both lock,
    which is what preserves the M-01 max_balance race.

    Args:
        account: The account this leg touches.
        delta: Its NET movement in this transaction (CREDIT positive).
        is_reversal / skip_receive_cap: The request flags that disable the
            ceiling. When the ceiling cannot fire, a credit needs no lock.

    Returns:
        True when a floor or ceiling check will run against this account.
    """
    if delta < 0:
        return account.account_type in _OVERDRAFT_GUARDED_ACCOUNT_TYPES
    if delta > 0:
        # Mirror the ceiling branch's own conditions exactly — locking for a
        # check that is about to be skipped is the bug this function fixes.
        return (
            account.account_type in _CEILING_GUARDED_ACCOUNT_TYPES
            and not is_reversal
            and not skip_receive_cap
            and account.user_id is not None
        )
    return False


async def _enforce_balance_guard(
    session: AsyncSession,
    request: PostTransactionRequest,
    accounts: dict[UUID, Account],
) -> None:
    """Lock every guarded leg and enforce overdraft + max_balance under it.

    Balance is ``SUM(ledger_entries)``, so no single row self-serialises
    concurrent writers; a check-then-write on the derived balance races two
    transactions past a cap or into overdraft. This is the single choke point
    (invariant #11) where a ``FOR UPDATE`` lock gates that check:

      * net debit  -> reject if it would overdraw available. The rejection is
        ``InsufficientFloat`` when the overdrawn account is the operator cash
        float (``system_cash_inflow``) — it must be pre-funded from the bank and
        may not go negative — and ``InsufficientFunds`` for a user wallet.
      * net credit -> reject (MaxBalanceExceeded) if it would breach max_balance,
        UNLESS ``is_reversal`` (a refund restores funds and may never be blocked)
        or ``skip_receive_cap`` (an earned payout such as an agent commission
        credit must land regardless of the agent's own cap — Story 20.3).

    Guarded accounts are ``financial_wallet`` (user wallet) and
    ``system_cash_inflow`` (the cash float): both get the overdraft floor. Only
    ``financial_wallet`` also carries the max_balance CEILING — the float has no
    ``user_id`` so the credit branch below skips it, and a credit to the float
    (a top-up) is never blocked. Other system / pool accounts
    (``operator_adjustment`` bank mirrors, merchant *collection* such as
    ``airtime_merchant_holding``, points) have neither floor nor cap and are
    skipped untouched.

    Locks are taken in account-id order and BEFORE any balance read, so two
    multi-wallet transactions (e.g. p2p, which locks both legs) can never
    deadlock on inverse lock orders. Each lock is held until the commit inside
    ``post_transaction`` — never across an external call (NFR-0130).

    Raises:
        InsufficientFunds (409): a debit would overdraw a user wallet.
        InsufficientFloat (409): a debit would overdraw the operator cash float.
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
        if _needs_lock(
            accounts[account_id],
            delta,
            is_reversal=request.is_reversal,
            skip_receive_cap=request.skip_receive_cap,
        )
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
            # This applies to the cash float too (no float overdraft) — the float
            # must be pre-funded from the bank before it can fund users. The error
            # differs so the operator learns to replenish the float rather than
            # the user being told to top up.
            if balance - reserved + delta < 0:
                if account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW:
                    raise InsufficientFloat()
                if account.account_type == ACCOUNT_TYPE_CASHBACK_PROVIDER:
                    raise InsufficientCashbackFunds()
                if account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET:
                    raise InsufficientCommissionBalance()
                raise InsufficientFunds()
        elif (
            not request.is_reversal
            and not request.skip_receive_cap
            and account.account_type in _CEILING_GUARDED_ACCOUNT_TYPES
            and account.user_id is not None
        ):
            # Ceiling applies to the spendable main wallet ONLY. The
            # account_type test is what excludes commission wallets, which are
            # user-owned but uncapped; the user_id check is kept because a
            # capped type always has an owner and it narrows the type for mypy.
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


# Postgres SQLSTATE 42P01 (undefined_table) — nextval() on a missing sequence
# raises this. Sequences aren't ORM-expressible, so we detect the code rather
# than a fragile message match.
_UNDEFINED_TABLE_SQLSTATE = "42P01"


def _tenant_sequence_name(tenant_id: UUID) -> str:
    """Return the reference sequence name for a tenant: `txn_ref_seq_<hex>`.

    The uuid hex is `[0-9a-f]{32}` — no user input — so it is safe to
    interpolate into raw SQL for `nextval` / `CREATE SEQUENCE`.
    """
    return f"txn_ref_seq_{tenant_id.hex}"


def build_reference(ts: datetime, seq: int) -> str:
    """Build a customer reference `S_<YYYYMMDDHHMMSS><NNNNNN>` (pure).

    Args:
        ts: The transaction's creation instant. The caller passes UTC; the
            14-digit timestamp segment is rendered from whatever tzinfo it
            carries via `strftime`, so pass an aware UTC datetime.
        seq: The per-tenant running number. Zero-padded to at least 6 digits;
            longer numbers keep all their digits.

    Returns:
        e.g. `S_20260715143022000042`.
    """
    return f"S_{ts.strftime('%Y%m%d%H%M%S')}{seq:06d}"


async def _next_reference_number(session: AsyncSession, tenant_id: UUID) -> int:
    """Draw the next per-tenant running number from its Postgres sequence.

    Uses a native SEQUENCE (`txn_ref_seq_<hex>`) for fast, concurrent-safe
    numbering. Sequences are not ORM-expressible, so `nextval` goes through
    raw `text()` — the ONE sanctioned raw-SQL exception here. Only the
    validated uuid-hex sequence name is interpolated; never user input.

    A rolled-back transaction may burn a number: GAPS ARE ACCEPTABLE and by
    design (a locking counter would serialise every money path — the M-01
    class of bug we explicitly avoid).

    The sequence is created up-front by the migration + seed. As a safety net
    (e.g. a tenant created outside seed), a missing sequence is created and the
    draw retried ONCE — this fallback runs at most once per tenant, never on the
    hot path. The first `nextval` runs inside a SAVEPOINT so its failure doesn't
    poison the outer transaction.

    Args:
        session: Async DB session with an open transaction.
        tenant_id: Tenant whose sequence to advance.

    Returns:
        The next running number (monotonic per tenant, gaps allowed).
    """
    seq_name = _tenant_sequence_name(tenant_id)
    nextval_stmt = text(f"SELECT nextval('\"{seq_name}\"')")
    try:
        async with session.begin_nested():
            result = await session.execute(nextval_stmt)
            return int(result.scalar_one())
    except ProgrammingError as exc:
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate != _UNDEFINED_TABLE_SQLSTATE:
            raise
        # Sequence not provisioned yet for this tenant — create and retry once.
        await session.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}"'))
        result = await session.execute(nextval_stmt)
        return int(result.scalar_one())


def signed_balance_expr() -> ColumnElement[Decimal]:
    """Per-row signed ledger amount: +amount for CREDIT, -amount for DEBIT.

    The ledger balance invariant (NFR-0100) is `SUM(CREDIT) - SUM(DEBIT)` per
    account; `func.sum(signed_balance_expr())` computes that directly. This is
    the ONE shared formula behind three call sites — `sum_completed_balance`
    below, the segment metric registry (`app.modules.segments.metrics._balance`),
    and the analytics per-currency balance aggregate
    (`app.modules.analytics.service._signed_balance_expr`, kept as a thin
    wrapper) — so a future ledger-schema change (e.g. a third entry direction)
    only needs one edit.

    The caller is responsible for filtering to COMPLETED status and the
    target account set before summing; this expression only encodes the sign.

    Both directions are matched explicitly (CREDIT and DEBIT) rather than
    using an `else_` catch-all for DEBIT: `entry_type` is CHECK-constrained to
    exactly those two values today, so this is a fail-safe, not a fix — a
    hypothetical future third entry direction contributes 0 (silently
    excluded) instead of being treated as a DEBIT by an unconditional
    `else_=-amount`.

    Returns:
        A CASE SQL expression suitable for `func.sum(...)`.
    """
    return case(
        (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount),
        (LedgerEntry.entry_type == ENTRY_DEBIT, -LedgerEntry.amount),
        else_=0,
    )


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
        select(func.coalesce(func.sum(signed_balance_expr()), 0)).where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
    )
    return Decimal(result.scalar_one() or 0)
