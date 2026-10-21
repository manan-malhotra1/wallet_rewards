"""Cached-balance updates take their row locks in canonical order.

`_enforce_balance_guard` locks the accounts it guards in account-id order
(invariant #11) specifically so two concurrent transfers touching the same pair
cannot grab them in opposite orders. `apply_deltas` takes a SECOND set of row
locks — one per `account_balance_snapshots` row — and must obey the same order.

It did not, and a mixed-service load run deadlocked: every process in the
Postgres deadlock report was the snapshot UPDATE. Transfers failed with HTTP 500.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    User,
)

_AMT = Decimal("10")


@pytest.mark.asyncio
async def test_opposing_transfers_between_two_accounts_do_not_deadlock(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify concurrent transfers in OPPOSITE directions never deadlock

    A -> B and B -> A present their legs in opposite order, so unsorted
    per-account locking deadlocks almost immediately under concurrency.
    """
    a = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_POINTS,
        currency="PTS",
    )
    b = Account(
        tenant_id=test_tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
    )
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)

    async def _move(debit, credit) -> None:
        async with session_factory() as s:
            await post_transaction(
                s,
                PostTransactionRequest(
                    tenant_id=test_tenant.id,
                    idempotency_key=f"lock-{uuid4().hex}",
                    transaction_type="reward_issuance",
                    currency="PTS",
                    entries=[
                        LedgerEntryRequest(account_id=debit, entry_type=ENTRY_DEBIT, amount=_AMT),
                        LedgerEntryRequest(account_id=credit, entry_type=ENTRY_CREDIT, amount=_AMT),
                    ],
                ),
            )

    # Alternate direction so the two legs are presented in opposing order.
    tasks = [_move(a.id, b.id) if n % 2 else _move(b.id, a.id) for n in range(16)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    deadlocks = [
        r for r in results if isinstance(r, BaseException) and "deadlock" in str(r).lower()
    ]
    assert not deadlocks, (
        f"{len(deadlocks)} of {len(tasks)} transfers deadlocked on the snapshot "
        "update — locks must be taken in canonical account-id order"
    )
    other = [r for r in results if isinstance(r, BaseException)]
    assert not other, f"unexpected failures: {other[:2]}"
