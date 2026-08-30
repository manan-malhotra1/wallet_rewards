"""Every cached balance equals the ledger it caches.

`account_balance_snapshots` is a derived cache, but the overdraft and
max_balance guards read it — so a snapshot that drifts from `ledger_entries` is
a money bug, not a stale-cache annoyance.

The cache is maintained at three sites (the INSERT in `post_transaction`, and
the two status flips in `airtime.service`). This test is the structural guard
that a FOURTH site added later cannot quietly bypass them: it re-derives every
snapshot straight from the ledger and compares. Any ledger movement that skips
`ledger/snapshots.py` fails the build here rather than silently mispricing a
customer's available balance.

Belt-and-braces alongside `test_ledger_sum_to_zero`, in the same spirit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.ledger.snapshots import sum_from_ledger
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    AccountBalanceSnapshot,
    Tenant,
)


async def _assert_every_snapshot_matches_the_ledger(session: AsyncSession) -> None:
    """Re-derive each snapshot from ledger_entries and compare."""
    snapshots = (await session.execute(select(AccountBalanceSnapshot))).scalars().all()
    assert snapshots, "expected at least one snapshot to verify"

    drifted: list[str] = []
    for snap in snapshots:
        balance, reserved = await sum_from_ledger(session, snap.account_id)
        if Decimal(snap.balance) != balance or Decimal(snap.reserved_balance) != reserved:
            drifted.append(
                f"  account {snap.account_id}: "
                f"cached=({snap.balance}, {snap.reserved_balance}) "
                f"ledger=({balance}, {reserved})"
            )

    assert not drifted, (
        "cached balances disagree with the ledger — a ledger write bypassed "
        "ledger/snapshots.py:\n" + "\n".join(drifted)
    )


@pytest.mark.asyncio
async def test_snapshots_match_the_ledger_after_posts(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify posting transactions leaves every cached balance ledger-accurate"""
    for i, amount in enumerate(("100", "37.50", "12.25"), start=1):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key=f"snap-inv-{i}",
                transaction_type="seed",
                currency="ZAR",
                entries=[
                    LedgerEntryRequest(
                        account_id=system_points_account.id,
                        entry_type=ENTRY_DEBIT,
                        amount=Decimal(amount),
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id,
                        entry_type=ENTRY_CREDIT,
                        amount=Decimal(amount),
                    ),
                ],
            ),
        )

    await _assert_every_snapshot_matches_the_ledger(db_session)


@pytest.mark.asyncio
async def test_snapshots_match_the_ledger_after_a_reversal(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify a reversal's opposite entries are folded into the cache too

    Reversals append opposite entries rather than editing the originals
    (ledger-invariants §1), so they flow through the same maintenance path —
    this pins that they are not special-cased out of it.
    """
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="snap-inv-orig",
            transaction_type="seed",
            currency="ZAR",
            entries=[
                LedgerEntryRequest(
                    account_id=system_points_account.id,
                    entry_type=ENTRY_DEBIT,
                    amount=Decimal("80"),
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id,
                    entry_type=ENTRY_CREDIT,
                    amount=Decimal("80"),
                ),
            ],
        ),
    )
    # The reversal: opposite directions, same amount, flagged so the ceiling
    # check stays fail-open (restoring funds may never be blocked).
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="snap-inv-rev",
            transaction_type="seed",
            currency="ZAR",
            is_reversal=True,
            entries=[
                LedgerEntryRequest(
                    account_id=user_wallet.id,
                    entry_type=ENTRY_DEBIT,
                    amount=Decimal("80"),
                ),
                LedgerEntryRequest(
                    account_id=system_points_account.id,
                    entry_type=ENTRY_CREDIT,
                    amount=Decimal("80"),
                ),
            ],
        ),
    )

    await _assert_every_snapshot_matches_the_ledger(db_session)
