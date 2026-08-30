"""The cached-balance reconciliation sweep.

`post_transaction`'s guards read `account_balance_snapshots`, so drift from
`ledger_entries` is a money bug. The CI invariant test proves consistency for
what the suite writes; this sweep is the runtime equivalent — it finds drift on
live data, says so loudly, and converges the cache back on the ledger.

Drift is forced here by writing a wrong snapshot directly, which is the only way
to test the detector independently of whatever causes drift in the wild.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.ledger.reconciliation import (
    drift_sweep_async,
    find_drift,
    repair_drift,
)
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    AccountBalanceSnapshot,
    Tenant,
)


async def _post(
    session: AsyncSession, tenant: Tenant, debit: Account, credit: Account, key: str
) -> None:
    """Post one balanced 100-unit transaction."""
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=key,
            transaction_type="seed",
            currency="ZAR",
            entries=[
                LedgerEntryRequest(
                    account_id=debit.id, entry_type=ENTRY_DEBIT, amount=Decimal("100")
                ),
                LedgerEntryRequest(
                    account_id=credit.id, entry_type=ENTRY_CREDIT, amount=Decimal("100")
                ),
            ],
        ),
    )


async def _corrupt(
    session: AsyncSession, account_id, balance: str, *, age_seconds: int = 0
) -> None:
    """Force a snapshot to disagree with the ledger.

    `age_seconds` backdates `snapshot_at`, which is what the sweep orders by —
    without it two accounts written by the same transaction share a timestamp
    and a LIMIT-1 batch picks between them arbitrarily.
    """
    # snapshot_at is always set, so the sweep's ordering is fully determined by
    # this helper rather than by whichever fixture wrote a row last.
    values: dict[str, object] = {
        "balance": Decimal(balance),
        "snapshot_at": datetime.now(UTC) - timedelta(seconds=age_seconds),
    }
    await session.execute(
        update(AccountBalanceSnapshot)
        .where(AccountBalanceSnapshot.account_id == account_id)
        .values(**values)
    )
    await session.commit()


async def _cached(session: AsyncSession, account_id) -> Decimal:
    """Read an account's cached balance."""
    return Decimal(
        (
            await session.execute(
                select(AccountBalanceSnapshot.balance).where(
                    AccountBalanceSnapshot.account_id == account_id
                )
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_sweep_reports_nothing_when_the_cache_agrees(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify a healthy cache produces no findings"""
    await _post(db_session, test_tenant, system_points_account, user_wallet, "sweep-ok")

    assert await find_drift(db_session) == []


@pytest.mark.asyncio
async def test_sweep_detects_a_drifted_balance(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify a snapshot that disagrees with the ledger is reported

    Reproduces the live signature: a cache short by exactly one posting.
    """
    await _post(db_session, test_tenant, system_points_account, user_wallet, "sweep-d1")
    await _corrupt(db_session, user_wallet.id, "50")

    drifted = await find_drift(db_session)

    assert [d.account_id for d in drifted] == [user_wallet.id]
    assert drifted[0].cached_balance == Decimal("50")
    assert drifted[0].ledger_balance == Decimal("100")


@pytest.mark.asyncio
async def test_sweep_repairs_drift_back_to_the_ledger(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify repair converges the cache on the ledger, which stays authoritative"""
    await _post(db_session, test_tenant, system_points_account, user_wallet, "sweep-r1")
    await _corrupt(db_session, user_wallet.id, "50")

    repaired = await repair_drift(db_session, await find_drift(db_session))
    await db_session.commit()

    assert repaired == 1
    assert await _cached(db_session, user_wallet.id) == Decimal("100")
    assert await find_drift(db_session) == []


@pytest.mark.asyncio
async def test_sweep_end_to_end_repairs_and_reports_a_count(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the task body finds, repairs and commits in one pass"""
    await _post(db_session, test_tenant, system_points_account, user_wallet, "sweep-e2e")
    await _corrupt(db_session, user_wallet.id, "-999")

    assert await drift_sweep_async(session_factory) == 1

    # Start a new transaction so this session sees the sweep's commit.
    await db_session.rollback()
    assert await _cached(db_session, user_wallet.id) == Decimal("100")


@pytest.mark.asyncio
async def test_sweep_batch_bounds_the_work_it_does(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
    system_points_account: Account,
) -> None:
    """Verify the batch cap is honoured

    Each verified account costs one aggregate over its whole history, so an
    unbounded sweep would reintroduce exactly the O(rows) cost the snapshot
    exists to avoid.
    """
    await _post(db_session, test_tenant, system_points_account, user_wallet, "sweep-b1")
    # Both drift; the system account is backdated so ordering is unambiguous.
    await _corrupt(db_session, user_wallet.id, "7")
    await _corrupt(db_session, system_points_account.id, "7", age_seconds=3600)

    newest_only = await find_drift(db_session, batch=1)
    assert [d.account_id for d in newest_only] == [user_wallet.id]

    assert len(await find_drift(db_session, batch=50)) == 2
