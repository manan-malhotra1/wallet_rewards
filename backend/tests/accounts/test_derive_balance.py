"""Round-trip cost and arithmetic of `accounts.derive_balance`.

`derive_balance` sits on the hot path of every balance-bearing money move (it
runs under the account write lock inside `ledger.post_transaction`), so the
number of round trips it makes is a correctness-adjacent property worth
pinning: a second query doubles both latency and lock hold time.

Guards the completed/pending split too, so collapsing the two aggregates into
one statement cannot silently swap the signs.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
)
from tests.conftest import test_engine


@contextlib.contextmanager
def count_statements() -> Iterator[list[str]]:
    """Record every SQL statement the test engine executes inside the block.

    Yields:
        A list that accumulates statement text; read it after the block.
    """
    seen: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)


async def _seed_entries(session: AsyncSession, tenant: Tenant, account: Account) -> None:
    """Give `account` a +100 completed balance and a 30 pending reservation.

    Writes entries directly rather than through `post_transaction` so the
    PENDING side can be created in isolation — the balanced-transaction API
    always completes both legs.
    """
    txn = Transaction(
        tenant_id=tenant.id,
        idempotency_key="derive-balance-roundtrip",
        transaction_type="seed",
        status="PENDING",
        amount=Decimal("100"),
        currency="ZAR",
    )
    session.add(txn)
    await session.flush()

    session.add_all(
        [
            LedgerEntry(
                transaction_id=txn.id,
                account_id=account.id,
                entry_type=ENTRY_CREDIT,
                amount=Decimal("150"),
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            ),
            LedgerEntry(
                transaction_id=txn.id,
                account_id=account.id,
                entry_type=ENTRY_DEBIT,
                amount=Decimal("50"),
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            ),
            LedgerEntry(
                transaction_id=txn.id,
                account_id=account.id,
                entry_type=ENTRY_DEBIT,
                amount=Decimal("30"),
                currency="ZAR",
                status=ENTRY_STATUS_PENDING,
            ),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_derive_balance_splits_completed_from_pending(
    db_session: AsyncSession, test_tenant: Tenant, user_wallet: Account
) -> None:
    """Verify completed entries drive balance and pending entries drive reserved"""
    await _seed_entries(db_session, test_tenant, user_wallet)

    balance, reserved = await derive_balance(db_session, user_wallet.id)

    # 150 CREDIT - 50 DEBIT completed; the 30 pending DEBIT is held, not spent.
    assert balance == Decimal("100")
    assert reserved == Decimal("30")


@pytest.mark.asyncio
async def test_derive_balance_uses_a_single_round_trip(
    db_session: AsyncSession, test_tenant: Tenant, user_wallet: Account
) -> None:
    """Verify balance and reserved are read in ONE statement, not two

    This runs under the account write lock on every money move, so a second
    aggregate over the same rows doubles the lock hold time for no new data.
    """
    await _seed_entries(db_session, test_tenant, user_wallet)

    with count_statements() as statements:
        await derive_balance(db_session, user_wallet.id)

    aggregates = [s for s in statements if "sum" in s.lower()]
    assert len(aggregates) == 1, (
        f"expected one aggregate over ledger_entries, got {len(aggregates)}:\n"
        + "\n".join(aggregates)
    )


@pytest.mark.asyncio
async def test_derive_balance_of_empty_account_is_zero(
    db_session: AsyncSession, user_wallet: Account
) -> None:
    """Verify an account with no entries reads as zero, not NULL"""
    balance, reserved = await derive_balance(db_session, user_wallet.id)

    assert balance == Decimal("0")
    assert reserved == Decimal("0")
