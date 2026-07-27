"""Core ledger posting.

The ledger is the single chokepoint for every state-mutating write to
`ledger_entries`. These tests cover the invariants enforced by the
service (NFR-0100, Pay-PRD-0170, Pay-PRD-0180, Pay-PRD-0200).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import (
    AccountNotFound,
    UnbalancedTransaction,
)
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    TXN_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Tenant,
)


def _balanced_p2p(
    src: Account, dst: Account, amount: Decimal, currency: str = "ZAR"
) -> list[LedgerEntryRequest]:
    """Helper: build a balanced 2-entry pair (debit src, credit dst)."""
    return [
        LedgerEntryRequest(account_id=src.id, entry_type=ENTRY_DEBIT, amount=amount),
        LedgerEntryRequest(account_id=dst.id, entry_type=ENTRY_CREDIT, amount=amount),
    ]


@pytest.mark.asyncio
async def test_post_transaction_happy_path(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify a balanced transaction is recorded and its entries appear"""
    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="happy-1",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced_p2p(system_points_account, user_wallet, Decimal("50")),
        ),
    )
    assert txn.status == TXN_STATUS_COMPLETED
    assert txn.amount == Decimal("50")

    rows = (
        (await db_session.execute(select(LedgerEntry).where(LedgerEntry.transaction_id == txn.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.status == ENTRY_STATUS_COMPLETED for r in rows)


@pytest.mark.asyncio
async def test_post_transaction_rejects_unbalanced_entries(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify a transaction whose credits and debits do not match is refused"""
    with pytest.raises(UnbalancedTransaction):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="unbalanced-1",
                transaction_type="seed",
                currency="ZAR",
                entries=[
                    LedgerEntryRequest(
                        account_id=system_points_account.id,
                        entry_type=ENTRY_DEBIT,
                        amount=Decimal("50"),
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id,
                        entry_type=ENTRY_CREDIT,
                        amount=Decimal("49"),  # off by 1 — must reject
                    ),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_post_transaction_rejects_single_entry(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
) -> None:
    """Verify a transaction with only one side is refused"""
    with pytest.raises(UnbalancedTransaction):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="single-1",
                transaction_type="seed",
                currency="ZAR",
                entries=[
                    LedgerEntryRequest(
                        account_id=user_wallet.id,
                        entry_type=ENTRY_CREDIT,
                        amount=Decimal("50"),
                    ),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_post_transaction_rejects_unknown_account(
    db_session: AsyncSession,
    test_tenant: Tenant,
    user_wallet: Account,
) -> None:
    """Verify a transaction naming an account that does not exist is refused"""
    with pytest.raises(AccountNotFound):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="unknown-account-1",
                transaction_type="seed",
                currency="ZAR",
                entries=[
                    LedgerEntryRequest(
                        account_id=uuid4(),  # not in DB
                        entry_type=ENTRY_DEBIT,
                        amount=Decimal("10"),
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id,
                        entry_type=ENTRY_CREDIT,
                        amount=Decimal("10"),
                    ),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_post_transaction_idempotent_returns_existing(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify submitting the same transaction twice records it only once

    Replaying the same idempotency_key returns the first transaction.

    Per Pay-PRD-0200, duplicate requests must NOT create new ledger entries.
    """
    request = PostTransactionRequest(
        tenant_id=test_tenant.id,
        idempotency_key="idem-1",
        transaction_type="seed",
        currency="ZAR",
        entries=_balanced_p2p(system_points_account, user_wallet, Decimal("10")),
    )
    first = await post_transaction(db_session, request)
    second = await post_transaction(db_session, request)

    assert first.id == second.id

    # Only 2 ledger entries should exist for this idempotency key.
    rows = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.transaction_id == first.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_post_transaction_rejects_zero_sum_zero_amounts(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify a transaction that moves no money is refused"""
    with pytest.raises(UnbalancedTransaction):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="zero-1",
                transaction_type="seed",
                currency="ZAR",
                entries=[
                    LedgerEntryRequest(
                        account_id=system_points_account.id,
                        entry_type=ENTRY_DEBIT,
                        amount=Decimal("0"),
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id,
                        entry_type=ENTRY_CREDIT,
                        amount=Decimal("0"),
                    ),
                ],
            ),
        )
