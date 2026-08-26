"""Batch execution — pass-2 re-validation and the postings (spec 2026-08-26 §8.4).

Separate from `service.py` because the approval workflow and the money movement
are independently testable, and because this file is where every ledger
invariant applies.

Two properties this file must never lose:
  - Idempotency per (batch, row). A retried apply must not double-pay, so the
    idempotency key is derived from the ROW ID — never a timestamp or a counter.
  - Per-row isolation. One failing row marks itself `failed` and the batch
    APPLIED_PARTIAL; it never rolls back rows that already posted.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_TERMINAL_STATUSES,
    BATCH_TYPE_DISBURSEMENT,
    BATCH_TYPE_WITHDRAWAL,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ROW_STATUS_FAILED,
    ROW_STATUS_POSTED,
    ROW_STATUS_VALID,
    Account,
    CommissionBatch,
    CommissionBatchRow,
    Transaction,
)

# Ledger transaction_type per batch kind, so a statement can tell a disbursement
# from a clawback without joining back to the batch.
_TXN_TYPE = {
    BATCH_TYPE_DISBURSEMENT: "commission_disbursement",
    BATCH_TYPE_WITHDRAWAL: "commission_withdrawal",
}


async def apply_batch(session: AsyncSession, batch: CommissionBatch) -> None:
    """Post every valid row, re-validating under the row lock.

    Balances can move between approval and apply — more commission accrues, or
    a single-user withdrawal lands — so the checker's snapshot is a decision
    aid, not a guarantee. A row that no longer covers its amount is marked
    `failed` with its reason and the batch lands APPLIED_PARTIAL, downloadable
    as a second rejects file.

    Args:
        session: Async DB session. NOT committed here — the caller
            (`approve_batch`) commits, so the status transition and the
            postings land together and a failure rolls back both.
        batch: The approved batch. Re-entry on a terminal batch is a no-op.

    Side effects:
        Posts 0..N transactions, mutates row statuses, sets the batch's
        terminal status.
    """
    if batch.status in BATCH_TERMINAL_STATUSES:
        return  # Already applied — re-entry is a no-op (spec §8.4).

    rows = list(
        (
            await session.execute(
                select(CommissionBatchRow).where(
                    CommissionBatchRow.batch_id == batch.id,
                    CommissionBatchRow.status == ROW_STATUS_VALID,
                )
            )
        )
        .scalars()
        .all()
    )

    failures = 0
    for row in rows:
        try:
            transaction = await _post_row(session, batch, row)
        except AppHTTPException as exc:
            # Per-row isolation: this row failed, the ones already posted stand.
            # Caught at AppHTTPException specifically — an unexpected error is
            # NOT swallowed into a row status, it aborts the whole apply.
            row.status = ROW_STATUS_FAILED
            row.failure_reason = exc.error_code
            failures += 1
            continue
        row.status = ROW_STATUS_POSTED
        row.transaction_id = transaction.id

    batch.status = BATCH_STATUS_APPLIED_PARTIAL if failures else BATCH_STATUS_APPLIED


async def _post_row(
    session: AsyncSession, batch: CommissionBatch, row: CommissionBatchRow
) -> Transaction:
    """Post one row: commission wallet -> main wallet, or -> the bank mirror.

    The DEBIT side is the commission wallet in both cases, so the ledger's
    non-negative floor (invariant #11, third shape) does the balance
    re-validation for us UNDER the FOR UPDATE lock. There is deliberately no
    separate check-then-act balance read here — that would race exactly the way
    the M-01 bug class does.

    `skip_receive_cap` is set because the credit is an earned payout the user
    already owns: a `max_balance` rejection would strand money in a wallet they
    cannot spend from (spec §8.4).

    Raises:
        AppHTTPException: propagated to `apply_batch`, which converts it into a
            per-row failure rather than aborting the batch.
    """
    destination_id = (
        await _main_wallet_id(session, batch, row)
        if batch.batch_type == BATCH_TYPE_DISBURSEMENT
        else batch.destination_account_id
    )
    if destination_id is None:
        raise AppHTTPException(
            422,
            "batch_destination_missing",
            "This withdrawal batch has no destination account.",
        )

    amount = Decimal(str(row.amount))
    assert row.resolved_account_id is not None, "a valid row always resolved a wallet"

    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=batch.tenant_id,
            # Derived from the ROW id, so a retried apply replays rather than
            # double-paying (Pay-PRD-0200).
            idempotency_key=f"commission-batch:{batch.id}:{row.id}",
            transaction_type=_TXN_TYPE[batch.batch_type],
            currency=row.currency,
            amount=amount,
            entries=[
                LedgerEntryRequest(row.resolved_account_id, ENTRY_DEBIT, amount),
                LedgerEntryRequest(destination_id, ENTRY_CREDIT, amount),
            ],
            skip_receive_cap=True,
        ),
    )


async def _main_wallet_id(
    session: AsyncSession, batch: CommissionBatch, row: CommissionBatchRow
) -> UUID:
    """The earner's main wallet in this row's currency.

    Raises:
        AppHTTPException 422 `main_wallet_missing`: unreachable once user-create
            provisioning is in place, kept as a backstop so a missing wallet
            fails this ROW rather than the whole batch.
    """
    account = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == batch.tenant_id,
                Account.user_id == row.resolved_user_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == row.currency,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise AppHTTPException(
            422,
            "main_wallet_missing",
            "The earner has no main wallet in this currency.",
        )
    return account.id
