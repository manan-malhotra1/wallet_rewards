"""Rewards service — issue points to a user when a rule fires.

Posts a balanced ledger transaction:
    DEBIT  system_points_issuance   (tenant's master source)
    CREDIT user's points_account

Inserts a `reward_events` row linking the rule + triggering event +
ledger entry. The UNIQUE INDEX on (user_id, rule_id, triggering_event_id)
is the idempotency guard (NFR-0110) — duplicates are caught at insert and
treated as no-op.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import (
    UserFinancialWalletMissing,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    REWARD_TYPE_CASHBACK,
    REWARD_TYPE_POINTS,
    Account,
    LedgerEntry,
    RewardEvent,
    Rule,
)

# Points always accrue in the platform "PTS" unit account — the single source
# of truth for the points currency, shared with the referral evaluator, seed,
# and pricing.service (which all key off "PTS"). Cashback pays in fiat instead.
POINTS_CURRENCY = "PTS"


async def _get_or_create_user_points_account(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> Account:
    """Return the user's points_account, provisioning one (in PTS) if absent.

    A user who earns a reward before ever holding points has no points_account:
    neither user creation nor the money paths provision one, and tenant
    provisioning only creates the PTS *instrument*, not per-user accounts. Rather
    than fail — which leaves a poisoned reward_outbox row the recon sweep retries
    to MAX_ATTEMPTS while the user silently never earns — auto-provision the one
    account the reward lands in. This is system provisioning: no admin actor and
    no audit row (mirrors the referral evaluator's `_ensure_user_account`).

    Both the internal wallet path and the external Kafka path funnel through
    `issue_points_reward`, so provisioning here covers every points-earn path,
    including users created before rewards were enabled.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: The reward recipient.

    Returns:
        The existing or newly-inserted (flushed, not committed) points Account.
        An account already present in ANY currency is reused as-is; a new one is
        created in `POINTS_CURRENCY`.

    Concurrency-safe: a first-ever race on the INSERT hits the
    `uq_accounts_user_scoped` unique index; the loser rolls back and re-reads the
    winner's row rather than surfacing a raw IntegrityError.
    """
    # Filter by currency too: the accounts unique index is
    # (tenant_id, user_id, account_type, currency), so a user MAY hold more than
    # one points account (one per currency). Points always accrue in PTS, so we
    # scope to POINTS_CURRENCY — matching the create below and avoiding a
    # MultipleResultsFound if a non-PTS points account ever exists.
    stmt = select(Account).where(
        Account.tenant_id == tenant_id,
        Account.user_id == user_id,
        Account.account_type == ACCOUNT_TYPE_POINTS,
        Account.currency == POINTS_CURRENCY,
    )
    account = (await session.execute(stmt)).scalar_one_or_none()
    if account is not None:
        return account
    account = Account(
        tenant_id=tenant_id,
        user_id=user_id,
        account_type=ACCOUNT_TYPE_POINTS,
        currency=POINTS_CURRENCY,
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return (await session.execute(stmt)).scalar_one()
    return account


async def get_or_create_system_points_issuance(
    session: AsyncSession, tenant_id: UUID, currency: str
) -> Account:
    """Return the per-(tenant, currency) master system_points_issuance account.

    The single source of truth for locating (and lazily creating) the DEBIT
    master that funds every points reward. Reused both by `issue_points_reward`
    and by the instrument-create provisioning path (Epic 28) so a new points
    currency shows up complete on the System Wallets page.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        currency: Points currency (e.g. 'PTS'). Case-insensitive.

    Returns:
        The existing or newly-inserted (flushed, not committed) Account.

    Concurrency-safe: a first-ever race on the INSERT hits the
    `uq_accounts_system_scoped` unique index; the loser rolls back and re-reads
    the winner's row rather than surfacing a raw IntegrityError.
    """
    currency = currency.upper()
    stmt = select(Account).where(
        Account.tenant_id == tenant_id,
        Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        Account.currency == currency,
        Account.user_id.is_(None),
    )
    account = (await session.execute(stmt)).scalar_one_or_none()
    if account is not None:
        return account
    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency=currency,
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return (await session.execute(stmt)).scalar_one()
    return account


async def _find_existing_reward_event(
    session: AsyncSession,
    user_id: UUID,
    rule_id: UUID,
    triggering_event_id: str,
) -> RewardEvent | None:
    """Check whether this (user, rule, event) triple already has a reward."""
    result = await session.execute(
        select(RewardEvent).where(
            RewardEvent.user_id == user_id,
            RewardEvent.rule_id == rule_id,
            RewardEvent.triggering_event_id == triggering_event_id,
        )
    )
    return result.scalar_one_or_none()


async def issue_points_reward(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    rule: Rule,
    triggering_event_id: str,
    reward_value: Decimal,
) -> RewardEvent:
    """Credit reward points to a user's points_account.

    Idempotent. If a reward_events row already exists for (user, rule,
    triggering_event_id), returns it without writing new ledger entries.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: User to be rewarded.
        rule: The rule that fired.
        triggering_event_id: External event_id (Kafka) or internal txn_id
            that caused this firing. Used for the idempotency guard.
        reward_value: Points to credit (typically rule.reward_value, but
            passed explicitly so callers can apply multipliers in future).

    Returns:
        The persisted RewardEvent.

    Side effects:
        Auto-provisions the user's points_account (in PTS) if they don't have
        one yet — see `_get_or_create_user_points_account`. Writes ledger +
        reward_events rows and commits.
    """
    # Fast-path: already issued — return existing row.
    existing = await _find_existing_reward_event(session, user_id, rule.id, triggering_event_id)
    if existing is not None:
        return existing

    user_points = await _get_or_create_user_points_account(session, tenant_id, user_id)
    system_issuance = await get_or_create_system_points_issuance(
        session, tenant_id, user_points.currency
    )

    # Epic 10 / WAL-78: apply any matching bonus multiplier BEFORE the
    # budget check + ledger write. The multiplied amount is what the
    # budget guards against and what ends up on the ledger. Lazy import
    # to avoid a service-layer cycle.
    from app.modules.multipliers.service import (
        resolve_multiplier_for_issuance,
    )

    multiplier = await resolve_multiplier_for_issuance(
        session, tenant_id=tenant_id, rule_id=rule.id, user_id=user_id
    )
    effective_value = (reward_value * multiplier).quantize(Decimal("0.000001"))

    # Phase G.1: every reward issuance is budget-checked BEFORE writing
    # the ledger. `check_budget_available` locks each matching budget row
    # FOR UPDATE, so two concurrent fires can't both pass at 99%
    # consumption. Raises BudgetExceeded on breach.
    from app.modules.budgets.service import check_budget_available

    await check_budget_available(
        session,
        tenant_id=tenant_id,
        rule_id=rule.id,
        currency=user_points.currency,
        amount=effective_value,
    )

    # Use the multiplied amount for ledger + reward_events from this point on.
    reward_value = effective_value

    # The idempotency_key on the underlying transaction is deterministic —
    # replays will hit the post_transaction idempotency guard, not write
    # a second transaction.
    idempotency_key = f"reward:{rule.id}:{user_id}:{triggering_event_id}"

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="reward_issuance",
            currency=user_points.currency,
            entries=[
                LedgerEntryRequest(
                    account_id=system_issuance.id,
                    entry_type=ENTRY_DEBIT,
                    amount=reward_value,
                ),
                LedgerEntryRequest(
                    account_id=user_points.id,
                    entry_type=ENTRY_CREDIT,
                    amount=reward_value,
                ),
            ],
            initiated_by=None,  # system-initiated
            amount=reward_value,
        ),
    )

    # Find the CREDIT entry on the user's points account so we can link it
    # from reward_events for audit traceability.
    credit_entry = (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.transaction_id == txn.id,
                LedgerEntry.account_id == user_points.id,
                LedgerEntry.entry_type == ENTRY_CREDIT,
            )
        )
    ).scalar_one_or_none()

    # Insert the reward_events row. The unique index catches concurrent
    # races — if another coroutine got here first, refetch and return.
    reward = RewardEvent(
        user_id=user_id,
        rule_id=rule.id,
        triggering_event_id=triggering_event_id,
        reward_type=REWARD_TYPE_POINTS,
        reward_value=reward_value,
        # Persist the multiplier so reports can distinguish base vs boosted.
        multiplier_applied=multiplier,
        ledger_entry_id=credit_entry.id if credit_entry else None,
    )
    session.add(reward)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _find_existing_reward_event(session, user_id, rule.id, triggering_event_id)
        if existing is None:
            raise  # unexpected — bubble up
        return existing

    await session.refresh(reward)
    return reward


async def _find_user_financial_wallet(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, currency: str
) -> Account:
    """Return the user's financial_wallet for this currency in the tenant, or raise."""
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
        raise UserFinancialWalletMissing()
    return account


async def _get_or_create_system_cash_inflow(
    session: AsyncSession, tenant_id: UUID, currency: str
) -> Account:
    """Return the tenant's system_cash_inflow account for this currency.

    Cashback promos are system-funded, so the debit master may not have been
    provisioned by seed for every currency. Create it on first use — the
    partial unique index `uq_accounts_system_scoped` keeps it single-instance
    per (tenant, currency); on a concurrent-create race we reload the winner.
    """
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
            Account.currency == currency.upper(),
            Account.user_id.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if account is not None:
        return account

    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency=currency.upper(),
    )
    session.add(account)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        account = (
            await session.execute(
                select(Account).where(
                    Account.tenant_id == tenant_id,
                    Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
                    Account.currency == currency.upper(),
                    Account.user_id.is_(None),
                )
            )
        ).scalar_one()
    return account


async def issue_cashback_reward(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    currency: str,
    amount: Decimal,
    rule_id: UUID,
    triggering_event_id: str,
) -> RewardEvent:
    """Credit a system-funded cashback reward to a user's financial_wallet.

    Mirrors `issue_points_reward` but moves money instead of points:
        DEBIT  system_cash_inflow (tenant master, this currency)
        CREDIT user's financial_wallet (this currency)

    Idempotent: if a reward_events row already exists for (user, rule,
    triggering_event_id) the existing row is returned without writing new
    ledger entries. Bonus multipliers are NOT applied — they multiply points
    only, never cashback (Pay-PRD-0623).

    The credit is CAP-EXEMPT (fail-open, invariant #11 corollary b): a reward
    may legitimately push a wallet past its `max_balance` and must never be
    blocked, so the transaction is posted with `skip_receive_cap=True`.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: User to be rewarded.
        currency: 3-letter ISO 4217 the reward is paid in; selects the user's
            wallet and the system_cash_inflow master.
        amount: Money to credit (> 0). Callers pass the rule's reward amount.
        rule_id: The rule that fired — recorded on the reward_event.
        triggering_event_id: Idempotency discriminator (Kafka event_id, txn id,
            or a synthetic referral key). Part of the unique guard.

    Returns:
        The persisted RewardEvent.

    Raises:
        UserFinancialWalletMissing: 422 — user has no wallet in this currency.
    """
    existing = await _find_existing_reward_event(session, user_id, rule_id, triggering_event_id)
    if existing is not None:
        return existing

    user_wallet = await _find_user_financial_wallet(session, tenant_id, user_id, currency)
    system_inflow = await _get_or_create_system_cash_inflow(session, tenant_id, currency)

    # Deterministic key → a replay hits post_transaction's idempotency guard
    # rather than writing a second money transaction.
    idempotency_key = f"cashback:{rule_id}:{user_id}:{triggering_event_id}"

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="cashback_reward",
            currency=currency.upper(),
            entries=[
                LedgerEntryRequest(
                    account_id=system_inflow.id,
                    entry_type=ENTRY_DEBIT,
                    amount=amount,
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id,
                    entry_type=ENTRY_CREDIT,
                    amount=amount,
                ),
            ],
            initiated_by=None,  # system-initiated promo credit
            amount=amount,
            # Cap-exempt: a reward may push the wallet past max_balance.
            skip_receive_cap=True,
        ),
    )

    credit_entry = (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.transaction_id == txn.id,
                LedgerEntry.account_id == user_wallet.id,
                LedgerEntry.entry_type == ENTRY_CREDIT,
            )
        )
    ).scalar_one_or_none()

    reward = RewardEvent(
        user_id=user_id,
        rule_id=rule_id,
        triggering_event_id=triggering_event_id,
        reward_type=REWARD_TYPE_CASHBACK,
        reward_value=amount,
        ledger_entry_id=credit_entry.id if credit_entry else None,
    )
    session.add(reward)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _find_existing_reward_event(session, user_id, rule_id, triggering_event_id)
        if existing is None:
            raise
        return existing

    await session.refresh(reward)
    return reward
