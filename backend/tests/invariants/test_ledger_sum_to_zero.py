"""System-wide ledger invariant: sum of all entries equals zero (NFR-0100).

This test runs against the test database after the rest of the suite
completes. It guards against any code path that accidentally writes
unbalanced entries — even though the ledger service rejects them, this is a
belt-and-braces structural check.

The invariant must always hold: for every COMPLETED entry, every CREDIT
amount is offset by an equal DEBIT amount somewhere in the system.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Tenant,
)


@pytest.mark.asyncio
async def test_ledger_sum_to_zero_holds_after_writes(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
    user_points: Account,
) -> None:
    """After arbitrary balanced writes, SUM(CREDIT) - SUM(DEBIT) is zero."""
    # Three sample transactions across the available accounts.
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="inv-1",
            transaction_type="seed",
            currency="ZAR",
            entries=[
                LedgerEntryRequest(
                    account_id=system_points_account.id,
                    entry_type=ENTRY_DEBIT,
                    amount=Decimal("100"),
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id,
                    entry_type=ENTRY_CREDIT,
                    amount=Decimal("100"),
                ),
            ],
        ),
    )
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="inv-2",
            transaction_type="seed",
            currency="PTS",
            entries=[
                LedgerEntryRequest(
                    account_id=system_points_account.id,
                    entry_type=ENTRY_DEBIT,
                    amount=Decimal("250"),
                ),
                LedgerEntryRequest(
                    account_id=user_points.id,
                    entry_type=ENTRY_CREDIT,
                    amount=Decimal("250"),
                ),
            ],
        ),
    )

    # System-wide sum across all COMPLETED entries.
    result = await db_session.execute(
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
        ).where(LedgerEntry.status == ENTRY_STATUS_COMPLETED)
    )
    net = Decimal(result.scalar_one() or 0)
    assert net == Decimal("0"), f"ledger drifted by {net}"


@pytest.mark.asyncio
async def test_ledger_entries_have_no_updated_at_column(
    db_session: AsyncSession,
) -> None:
    """Belt-and-braces: confirm the table truly lacks `updated_at`.

    This is a structural guarantee for the append-only invariant — if
    someone adds `updated_at` later, the test fails and they revisit the
    decision intentionally.
    """
    from sqlalchemy import text

    rows = (
        await db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'ledger_entries'"
            )
        )
    ).all()
    columns = {row[0] for row in rows}
    assert "updated_at" not in columns, (
        "ledger_entries must remain append-only — no updated_at column"
    )
