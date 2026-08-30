"""Cached account balances stay in step with the ledger.

`account_balance_snapshots` is a cache, never the source of truth — but the
overdraft and max_balance guards read it, so a snapshot that drifts from
`ledger_entries` is a money bug, not a stale-cache annoyance.

Balance reads used to aggregate an account's whole history on every call, which
grows without bound on shared accounts (the tenant's `system_fee_collected`
takes an entry from EVERY transaction: 432k rows/day at 5 TPS, measured at
931ms per read by 5M rows — while holding the account write lock).

These tests pin the two properties that make the cache trustworthy: it is
updated in the same transaction as the entries that move it, and reading it
costs one indexed row rather than a scan.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    AccountBalanceSnapshot,
    Tenant,
)
from tests.conftest import test_engine


@contextlib.contextmanager
def capture_sql() -> Iterator[list[str]]:
    """Record every SQL statement the test engine executes inside the block."""
    seen: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    from sqlalchemy import event

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)


async def _snapshot(session: AsyncSession, account_id) -> AccountBalanceSnapshot | None:
    """Read an account's cached balance row, or None when absent."""
    return (
        await session.execute(
            select(AccountBalanceSnapshot).where(AccountBalanceSnapshot.account_id == account_id)
        )
    ).scalar_one_or_none()


async def _post(
    session: AsyncSession,
    tenant: Tenant,
    debit: Account,
    credit: Account,
    amount: str,
    key: str,
) -> None:
    """Post one balanced COMPLETED transaction between two accounts."""
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=key,
            transaction_type="seed",
            currency="ZAR",
            entries=[
                LedgerEntryRequest(
                    account_id=debit.id, entry_type=ENTRY_DEBIT, amount=Decimal(amount)
                ),
                LedgerEntryRequest(
                    account_id=credit.id, entry_type=ENTRY_CREDIT, amount=Decimal(amount)
                ),
            ],
        ),
    )


@pytest.mark.asyncio
async def test_posting_a_transaction_updates_both_snapshots(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify each leg's cached balance moves with the entries that caused it"""
    await _post(db_session, test_tenant, system_points_account, user_wallet, "100", "snap-1")

    credited = await _snapshot(db_session, user_wallet.id)
    debited = await _snapshot(db_session, system_points_account.id)

    assert credited is not None, "the credited account should have a snapshot"
    assert Decimal(credited.balance) == Decimal("100")
    assert debited is not None, "the debited account should have a snapshot"
    assert Decimal(debited.balance) == Decimal("-100")


@pytest.mark.asyncio
async def test_snapshots_accumulate_across_transactions(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify repeated posts accumulate rather than overwrite

    A shared account (the tenant fee wallet) takes an entry from every
    transaction, so the cache must fold each one in.
    """
    await _post(db_session, test_tenant, system_points_account, user_wallet, "100", "snap-a")
    await _post(db_session, test_tenant, system_points_account, user_wallet, "25", "snap-b")
    await _post(db_session, test_tenant, user_wallet, system_points_account, "40", "snap-c")

    snap = await _snapshot(db_session, user_wallet.id)
    assert snap is not None
    # +100 +25 -40
    assert Decimal(snap.balance) == Decimal("85")


@pytest.mark.asyncio
async def test_snapshot_matches_the_ledger_it_caches(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify the cached balance equals what the ledger says, for every account

    This is the property the guards depend on. If it ever fails, the cache is
    lying to a money decision.
    """
    await _post(db_session, test_tenant, system_points_account, user_wallet, "70", "snap-m1")
    await _post(db_session, test_tenant, user_wallet, system_points_account, "15", "snap-m2")

    for account in (user_wallet, system_points_account):
        snap = await _snapshot(db_session, account.id)
        assert snap is not None, f"no snapshot for {account.id}"
        from app.modules.ledger.service import sum_completed_balance

        assert Decimal(snap.balance) == await sum_completed_balance(db_session, account.id)


@pytest.mark.asyncio
async def test_reading_a_balance_does_not_scan_the_ledger(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify a balance read costs an indexed row, not an aggregate over history

    This is the whole point: the cost of reading a balance must stop growing
    with the number of entries the account has accumulated.
    """
    await _post(db_session, test_tenant, system_points_account, user_wallet, "10", "snap-read")

    with capture_sql() as statements:
        balance, _reserved = await derive_balance(db_session, user_wallet.id)

    assert balance == Decimal("10")
    ledger_scans = [s for s in statements if "coalesce(sum(" in s and "ledger_entries" in s]
    assert ledger_scans == [], (
        "reading a balance should hit the snapshot, not aggregate ledger_entries:\n"
        + "\n".join(ledger_scans)
    )
