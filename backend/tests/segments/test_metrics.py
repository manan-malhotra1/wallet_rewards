"""Per-metric correctness tests for the segment metric registry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.metrics import METRIC_BUILDERS, compute_metric
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
    User,
)
from app.shared.models.accounts import ACCOUNT_TYPE_FINANCIAL_WALLET


def _txn(
    tenant_id: UUID,
    user_id: UUID,
    amount: str,
    txn_type: str = "p2p",
    status: str = "COMPLETED",
    days_ago: int = 0,
) -> Transaction:
    """Build a minimal (unsaved) Transaction row for metric tests.

    Args:
        tenant_id: Owning tenant.
        user_id: Initiating user (used as the metric's group-by key).
        amount: Decimal amount as a string (avoids float rounding).
        txn_type: `transaction_type` filter value.
        status: Transaction status; only COMPLETED rows count for the metrics.
        days_ago: Backdates `created_at` for window-based metric tests.

    Returns:
        A `Transaction` instance not yet added to any session.
    """
    return Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"k-{user_id}-{amount}-{txn_type}-{days_ago}",
        transaction_type=txn_type,
        status=status,
        initiated_by=user_id,
        amount=Decimal(amount),
        currency="ZAR",
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def test_registry_matches_dsl_vocabulary() -> None:
    """Registry names and DSL vocabulary must never drift (enforces criteria.py's contract)."""
    from app.modules.segments.criteria import ALL_METRICS

    assert set(METRIC_BUILDERS) == set(ALL_METRICS)


@pytest.mark.asyncio
async def test_txn_count_with_type_and_window(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """txn_count only counts COMPLETED rows matching the type + window filters."""
    db_session.add_all(
        [
            _txn(test_tenant.id, test_user.id, "10"),
            _txn(test_tenant.id, test_user.id, "20"),
            _txn(test_tenant.id, test_user.id, "30", txn_type="airtime"),
            _txn(test_tenant.id, test_user.id, "40", days_ago=120),
            _txn(test_tenant.id, test_user.id, "50", status="FAILED"),
        ]
    )
    await db_session.flush()

    values = await compute_metric(
        db_session, test_tenant.id, "txn_count", txn_type="p2p", window_days=90
    )
    assert values[test_user.id] == Decimal(2)


@pytest.mark.asyncio
async def test_txn_sum_scopes_to_tenant(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, other_tenant: Tenant
) -> None:
    """txn_sum totals COMPLETED amounts per user and never crosses tenants."""
    db_session.add(_txn(test_tenant.id, test_user.id, "12.50"))
    await db_session.flush()
    values = await compute_metric(db_session, test_tenant.id, "txn_sum")
    assert values[test_user.id] == Decimal("12.50")
    other_values = await compute_metric(db_session, other_tenant.id, "txn_sum")
    assert test_user.id not in other_values


@pytest.mark.asyncio
async def test_account_age_days(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """account_age_days returns a non-negative value for every tenant user."""
    values = await compute_metric(db_session, test_tenant.id, "account_age_days")
    assert values[test_user.id] >= Decimal(0)


@pytest.mark.asyncio
async def test_days_since_last_txn_defaults_large_for_never_transacted(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A user with no COMPLETED transaction gets the 99999-day sentinel."""
    values = await compute_metric(db_session, test_tenant.id, "days_since_last_txn")
    assert values[test_user.id] == Decimal(99999)

    db_session.add(_txn(test_tenant.id, test_user.id, "10", days_ago=3))
    await db_session.flush()
    values = await compute_metric(db_session, test_tenant.id, "days_since_last_txn")
    assert Decimal(2) <= values[test_user.id] <= Decimal(4)


@pytest.mark.asyncio
async def test_wallet_balance_nets_completed_credits_and_debits(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """wallet_balance is CREDIT minus DEBIT over COMPLETED ledger entries only."""
    account = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(account)
    await db_session.flush()

    # Ledger entries require a parent transaction (FK); its own fields are
    # irrelevant to the balance computation, so reuse the minimal `_txn` factory.
    txn = _txn(test_tenant.id, test_user.id, "100")
    db_session.add(txn)
    await db_session.flush()

    db_session.add_all(
        [
            LedgerEntry(
                transaction_id=txn.id,
                account_id=account.id,
                entry_type=ENTRY_CREDIT,
                amount=Decimal("100"),
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            ),
            LedgerEntry(
                transaction_id=txn.id,
                account_id=account.id,
                entry_type=ENTRY_DEBIT,
                amount=Decimal("40"),
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            ),
        ]
    )
    await db_session.flush()

    values = await compute_metric(db_session, test_tenant.id, "wallet_balance")
    assert values[test_user.id] == Decimal("60")
