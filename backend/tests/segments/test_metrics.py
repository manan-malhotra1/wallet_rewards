"""Per-metric correctness tests for the segment metric registry.

Transaction metrics (`txn_count`, `txn_sum`, `days_since_last_txn`) are
wallet-attributed (see `app.modules.segments.metrics` module docstring):
they key off the user's own `financial_wallet` Account -> LedgerEntry ->
Transaction, never off `Transaction.initiated_by`. `_wallet_txn` below is the
one local factory that builds that shape; every wallet-attributed test reuses
it instead of hand-rolling ledger rows per test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.criteria import ALL_METRICS
from app.modules.segments.metrics import METRIC_BUILDERS, NEVER_TRANSACTED_DAYS, compute_metric
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS_REDEMPTION,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    REFERRAL_STATUS_REWARDED,
    TXN_STATUS_COMPLETED,
    Account,
    InternalRedemption,
    LedgerEntry,
    Referral,
    RewardEvent,
    Rule,
    Tenant,
    Transaction,
    User,
)


async def _wallet_account(
    db_session: AsyncSession, tenant_id: UUID, user_id: UUID | None, currency: str = "ZAR"
) -> Account:
    """Create + flush a financial_wallet account.

    Args:
        db_session: Async DB session.
        tenant_id: Owning tenant.
        user_id: Account owner, or None for a system/counterparty wallet that
            deliberately shouldn't attribute to any user in these tests (the
            `user_id` FK requires a real `users.id` row, so a placeholder
            UUID would violate it — None is the correct "don't care" value).
        currency: Wallet currency (defaults to ZAR, the tenant fixtures' base).

    Returns:
        The persisted (flushed, not committed) `Account`.
    """
    account = Account(
        tenant_id=tenant_id,
        user_id=user_id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
    )
    db_session.add(account)
    await db_session.flush()
    return account


async def _wallet_txn(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    debit_account: Account,
    credit_account: Account,
    amount: str,
    txn_type: str = "p2p",
    days_ago: int = 0,
    initiated_by: UUID | None = None,
    currency: str = "ZAR",
) -> Transaction:
    """Create a COMPLETED transaction with a DEBIT + CREDIT leg on two wallets.

    This is the wallet-attributed shape the reworked metrics key off: a
    LedgerEntry on `debit_account` and one on `credit_account`, both
    COMPLETED, joined to a COMPLETED `Transaction`. `initiated_by` defaults to
    the debiting user but can be overridden to any user — deliberately, so
    tests can prove attribution follows the wallet touch, not this field (the
    C1 regression this fix addresses).

    Args:
        db_session: Async DB session.
        tenant_id: Owning tenant for the transaction and both accounts.
        debit_account: Wallet that receives the DEBIT leg.
        credit_account: Wallet that receives the CREDIT leg.
        amount: Decimal amount as a string (avoids float rounding).
        txn_type: `transaction_type` filter value.
        days_ago: Backdates `created_at` for window-based metric tests.
        initiated_by: Overrides the transaction's `initiated_by`; defaults to
            `debit_account.user_id`.
        currency: Currency for the transaction and both ledger legs — should
            match the wallets' own currency (defaults to ZAR).

    Returns:
        The persisted (flushed) `Transaction`.
    """
    created_at = datetime.now(UTC) - timedelta(days=days_ago)
    txn = Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"k-{uuid4()}",
        transaction_type=txn_type,
        status=TXN_STATUS_COMPLETED,
        initiated_by=initiated_by if initiated_by is not None else debit_account.user_id,
        amount=Decimal(amount),
        currency=currency,
        created_at=created_at,
    )
    db_session.add(txn)
    await db_session.flush()
    db_session.add_all(
        [
            LedgerEntry(
                transaction_id=txn.id,
                account_id=debit_account.id,
                entry_type=ENTRY_DEBIT,
                amount=Decimal(amount),
                currency=currency,
                status=ENTRY_STATUS_COMPLETED,
                created_at=created_at,
            ),
            LedgerEntry(
                transaction_id=txn.id,
                account_id=credit_account.id,
                entry_type=ENTRY_CREDIT,
                amount=Decimal(amount),
                currency=currency,
                status=ENTRY_STATUS_COMPLETED,
                created_at=created_at,
            ),
        ]
    )
    await db_session.flush()
    return txn


def test_registry_matches_dsl_vocabulary() -> None:
    """Registry names and DSL vocabulary must never drift (enforces criteria.py's contract)."""
    assert METRIC_BUILDERS.keys() == ALL_METRICS


@pytest.mark.asyncio
async def test_txn_metrics_are_wallet_attributed_and_independent_per_user(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    user_factory: Any,
) -> None:
    """Two users get correct, independent values from one compute (set-based property).

    Also the core wallet-attribution behaviour: user B receives no
    `initiated_by` row at all under the old scheme, yet must be counted here
    because the CREDIT leg touches B's own wallet.
    """
    user_b = await user_factory(test_tenant)
    wallet_b = await _wallet_account(db_session, test_tenant.id, user_b.id)

    # A -> B, 100 (both wallets touched).
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=wallet_b, amount="100"
    )
    # A separate cash-in-style txn crediting A only (B untouched).
    system_wallet = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=system_wallet,
        credit_account=user_wallet,
        amount="30",
        txn_type="cash_in",
    )

    counts = await compute_metric(db_session, test_tenant.id, "txn_count")
    sums = await compute_metric(db_session, test_tenant.id, "txn_sum")

    assert counts[test_user.id] == Decimal(2)
    assert counts[user_b.id] == Decimal(1)
    assert sums[test_user.id] == Decimal(130)
    assert sums[user_b.id] == Decimal(100)


@pytest.mark.asyncio
async def test_txn_sum_scopes_to_tenant(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    other_tenant: Tenant,
    user_factory: Any,
) -> None:
    """Cross-tenant: each tenant's compute sees only its own wallet activity."""
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="12.50",
    )

    other_user = await user_factory(other_tenant)
    other_wallet = await _wallet_account(db_session, other_tenant.id, other_user.id, currency="USD")
    other_counterpart = await _wallet_account(db_session, other_tenant.id, None, currency="USD")
    await _wallet_txn(
        db_session,
        other_tenant.id,
        debit_account=other_wallet,
        credit_account=other_counterpart,
        amount="999",
        currency="USD",
    )

    values = await compute_metric(db_session, test_tenant.id, "txn_sum")
    other_values = await compute_metric(db_session, other_tenant.id, "txn_sum")

    assert values[test_user.id] == Decimal("12.50")
    assert test_user.id not in other_values
    assert other_user.id not in values
    assert other_values[other_user.id] == Decimal(999)


@pytest.mark.asyncio
async def test_txn_sum_is_scoped_to_tenant_base_currency(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A second wallet in another currency counts toward txn_count but not txn_sum.

    `test_tenant`'s base currency is ZAR (see `tests/conftest.py::test_tenant`).
    A USD wallet for the SAME user must not have its amount folded into
    txn_sum — that would silently mix currencies — but the transaction itself
    still counts toward txn_count, which stays currency-agnostic.
    """
    zar_counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=zar_counterpart,
        amount="50",
    )

    usd_wallet = await _wallet_account(db_session, test_tenant.id, test_user.id, currency="USD")
    usd_counterpart = await _wallet_account(db_session, test_tenant.id, None, currency="USD")
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=usd_wallet,
        credit_account=usd_counterpart,
        amount="1000",
        currency="USD",
    )

    counts = await compute_metric(db_session, test_tenant.id, "txn_count")
    sums = await compute_metric(db_session, test_tenant.id, "txn_sum")

    assert counts[test_user.id] == Decimal(2)
    assert sums[test_user.id] == Decimal(50)


@pytest.mark.asyncio
async def test_txn_count_receive_side_attribution_ignores_initiated_by(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    user_factory: Any,
) -> None:
    """C1 regression: a CREDIT to user B's wallet counts for B even though
    `initiated_by` is user A (mirrors the cash-in mis-attribution bug — the
    agent initiates, but the customer's wallet is the one that moved)."""
    user_b = await user_factory(test_tenant)
    wallet_b = await _wallet_account(db_session, test_tenant.id, user_b.id)

    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=wallet_b,
        amount="75",
        txn_type="cash_in",
        initiated_by=test_user.id,
    )

    counts = await compute_metric(db_session, test_tenant.id, "txn_count")
    assert counts[user_b.id] == Decimal(1)


@pytest.mark.asyncio
async def test_txn_count_and_sum_handle_two_entries_on_the_same_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Fanout regression (M1): a transaction with two COMPLETED entries on ONE
    wallet — mirrors the real agent cash-in shape, where the principal DEBIT
    and the commission CREDIT are netted onto the same wallet. `txn_count`
    must apply the DISTINCT(transaction_id) guard (count the transaction
    once, not once per entry); `txn_sum` sums both legs (gross, not net)."""
    txn = Transaction(
        tenant_id=test_tenant.id,
        idempotency_key=f"k-{uuid4()}",
        transaction_type="cash_in",
        status=TXN_STATUS_COMPLETED,
        initiated_by=test_user.id,
        amount=Decimal("100"),
        currency="ZAR",
    )
    db_session.add(txn)
    await db_session.flush()
    db_session.add_all(
        [
            LedgerEntry(
                transaction_id=txn.id,
                account_id=user_wallet.id,
                entry_type=ENTRY_DEBIT,
                amount=Decimal("100"),
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            ),
            LedgerEntry(
                transaction_id=txn.id,
                account_id=user_wallet.id,
                entry_type=ENTRY_CREDIT,
                amount=Decimal("15"),
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            ),
        ]
    )
    await db_session.flush()

    counts = await compute_metric(db_session, test_tenant.id, "txn_count")
    sums = await compute_metric(db_session, test_tenant.id, "txn_sum")

    assert counts[test_user.id] == Decimal(1)
    assert sums[test_user.id] == Decimal(115)


@pytest.mark.asyncio
async def test_txn_count_with_type_and_window(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """txn_count only counts wallet-touching COMPLETED rows matching type + window."""
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="10",
    )
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="20",
    )
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="30",
        txn_type="airtime_recharge",
    )
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="40",
        days_ago=120,
    )

    values = await compute_metric(
        db_session, test_tenant.id, "txn_count", txn_type="p2p", window_days=90
    )
    assert values[test_user.id] == Decimal(2)


@pytest.mark.asyncio
async def test_account_age_days_bounds_for_a_thirty_day_old_user(
    db_session: AsyncSession, test_tenant: Tenant, user_factory: Any
) -> None:
    """A user created ~30 days ago reports an age in [29, 31] days."""
    user = await user_factory(test_tenant)
    user.created_at = datetime.now(UTC) - timedelta(days=30)
    db_session.add(user)
    await db_session.flush()

    values = await compute_metric(db_session, test_tenant.id, "account_age_days")
    assert Decimal(29) <= values[user.id] <= Decimal(31)


@pytest.mark.asyncio
async def test_days_since_last_txn_defaults_large_for_never_transacted(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A user with no wallet-touching COMPLETED transaction gets the sentinel."""
    values = await compute_metric(db_session, test_tenant.id, "days_since_last_txn")
    assert values[test_user.id] == NEVER_TRANSACTED_DAYS
    assert values[test_user.id] == Decimal(99999)

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="10",
        days_ago=3,
    )
    values = await compute_metric(db_session, test_tenant.id, "days_since_last_txn")
    assert Decimal(2) <= values[test_user.id] <= Decimal(4)


@pytest.mark.asyncio
async def test_wallet_balance_nets_completed_credits_and_debits(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """wallet_balance is CREDIT minus DEBIT over COMPLETED ledger entries, base-currency scoped."""
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    # +100 into the wallet, then -40 out — net 60.
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=counterpart,
        credit_account=user_wallet,
        amount="100",
    )
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="40",
    )

    values = await compute_metric(db_session, test_tenant.id, "wallet_balance")
    assert values[test_user.id] == Decimal("60")


@pytest.mark.asyncio
async def test_points_balance_nets_completed_credits_and_debits(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_points: Account
) -> None:
    """points_balance sums CREDIT minus DEBIT over the user's PTS account."""
    other_points = Account(
        tenant_id=test_tenant.id,
        account_type=ACCOUNT_TYPE_POINTS_REDEMPTION,
        currency="PTS",
    )
    db_session.add(other_points)
    await db_session.flush()

    txn = Transaction(
        tenant_id=test_tenant.id,
        idempotency_key=f"k-{uuid4()}",
        transaction_type="reward_issuance",
        status=TXN_STATUS_COMPLETED,
        amount=Decimal("200"),
        currency="PTS",
    )
    db_session.add(txn)
    await db_session.flush()
    db_session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=user_points.id,
            entry_type=ENTRY_CREDIT,
            amount=Decimal("200"),
            currency="PTS",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    await db_session.flush()

    values = await compute_metric(db_session, test_tenant.id, "points_balance")
    assert values[test_user.id] == Decimal(200)


@pytest.mark.asyncio
async def test_points_redeemed_sums_internal_redemptions(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_points: Account
) -> None:
    """points_redeemed sums InternalRedemption.points_amount per user.

    Internal redemptions settle synchronously inside one transaction, so every
    row is a completed one — there is no status to filter on, which is why this
    no longer seeds a PENDING row to be excluded.
    """

    async def _redeem(points: str, fiat: str) -> None:
        """Insert one settled points-to-wallet redemption for the test user."""
        legs = []
        for kind, amount, currency in (("redemption", points, "PTS"), ("payout", fiat, "ZAR")):
            txn = Transaction(
                tenant_id=test_tenant.id,
                idempotency_key=f"{kind}-{uuid4()}",
                transaction_type=kind,
                status=TXN_STATUS_COMPLETED,
                initiated_by=test_user.id,
                amount=Decimal(amount),
                currency=currency,
            )
            db_session.add(txn)
            legs.append(txn)
        await db_session.flush()
        db_session.add(
            InternalRedemption(
                tenant_id=test_tenant.id,
                user_id=test_user.id,
                points_transaction_id=legs[0].id,
                payout_transaction_id=legs[1].id,
                currency="ZAR",
                points_amount=Decimal(points),
                fiat_amount=Decimal(fiat),
                points_per_unit=Decimal("100"),
                value_per_unit=Decimal("10"),
                idempotency_key=f"redeem-{uuid4()}",
            )
        )
        await db_session.flush()

    # Two redemptions, so the metric is proven to SUM rather than take the last.
    await _redeem("50", "5.00")
    await _redeem("30", "3.00")

    values = await compute_metric(db_session, test_tenant.id, "points_redeemed")
    assert values[test_user.id] == Decimal(80)


@pytest.mark.asyncio
async def test_rewards_earned_counts_events_not_points_value(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """rewards_earned counts RewardEvent rows — not their reward_value."""
    rule = Rule(
        tenant_id=test_tenant.id,
        name="first p2p",
        rule_type="first_time",
        transaction_type="p2p",
        reward_type="points",
        reward_value=Decimal("100"),
    )
    db_session.add(rule)
    await db_session.flush()
    db_session.add_all(
        [
            RewardEvent(
                user_id=test_user.id,
                rule_id=rule.id,
                triggering_event_id=uuid4().hex,
                reward_type="points",
                reward_value=Decimal("100"),
            ),
            RewardEvent(
                user_id=test_user.id,
                rule_id=rule.id,
                triggering_event_id=uuid4().hex,
                reward_type="points",
                reward_value=Decimal("250"),
            ),
        ]
    )
    await db_session.flush()

    values = await compute_metric(db_session, test_tenant.id, "rewards_earned")
    assert values[test_user.id] == Decimal(2)


@pytest.mark.asyncio
async def test_referral_count_counts_only_rewarded_referrals(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_factory: Any
) -> None:
    """referral_count only counts REFERRAL_STATUS_REWARDED rows for the referrer."""
    referee = await user_factory(test_tenant)
    db_session.add(
        Referral(
            tenant_id=test_tenant.id,
            referrer_user_id=test_user.id,
            referred_user_id=referee.id,
            code="ABCD1234",
            status=REFERRAL_STATUS_REWARDED,
        )
    )
    await db_session.flush()

    values = await compute_metric(db_session, test_tenant.id, "referral_count")
    assert values[test_user.id] == Decimal(1)


@pytest.mark.asyncio
async def test_compute_metric_rejects_unregistered_metric_name(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """An unregistered metric name raises KeyError rather than silently returning {}."""
    with pytest.raises(KeyError):
        await compute_metric(db_session, test_tenant.id, "not_a_real_metric")


@pytest.mark.asyncio
async def test_compute_metric_is_deterministic_given_an_explicit_now(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Passing an explicit `now` yields identical results across two calls."""
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        amount="10",
        days_ago=3,
    )

    frozen_now = datetime.now(UTC)
    first = await compute_metric(db_session, test_tenant.id, "days_since_last_txn", now=frozen_now)
    second = await compute_metric(db_session, test_tenant.id, "days_since_last_txn", now=frozen_now)
    assert first == second
