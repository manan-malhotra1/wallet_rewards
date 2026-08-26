"""Quorum, terminal rejection, postings, drift and idempotency (spec §8.3-8.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.commission_batches.apply import apply_batch
from app.modules.commission_batches.service import (
    approve_batch,
    create_batch,
    reject_batch,
)
from app.shared.exceptions import (
    AppHTTPException,
    BatchDuplicateApprover,
    BatchInvalidState,
    SelfApprovalForbidden,
)
from app.shared.models import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_STATUS_REJECTED,
    BATCH_TYPE_DISBURSEMENT,
    BATCH_TYPE_WITHDRAWAL,
    ENTRY_CREDIT,
    ROW_STATUS_FAILED,
    ROW_STATUS_POSTED,
    ApprovalPolicy,
    CommissionBatchRow,
    LedgerEntry,
)
from tests.commission_batches.conftest import BatchFixture


def _csv(*lines: str) -> str:
    """A batch file with the standard header."""
    return "msisdn,currency,amount,note\n" + "".join(f"{line}\n" for line in lines)


async def _pending(
    db_session: AsyncSession,
    fx: BatchFixture,
    maker,
    *,
    batch_type: str = BATCH_TYPE_DISBURSEMENT,
    amount: str = "40",
):
    """Stage a one-row PENDING batch."""
    return await create_batch(
        db_session,
        tenant_id=fx.tenant.id,
        batch_type=batch_type,
        file_name="nov.csv",
        content=_csv(f"{fx.agent_msisdn},ZAR,{amount},Verified"),
        admin=maker,
        destination_account_id=(
            fx.bank_mirror.id if batch_type == BATCH_TYPE_WITHDRAWAL else None
        ),
    )


async def _rows(session: AsyncSession, batch_id) -> list[CommissionBatchRow]:
    """Every row of a batch."""
    return list(
        (
            await session.execute(
                select(CommissionBatchRow).where(CommissionBatchRow.batch_id == batch_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_maker_cannot_approve_their_own_batch(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """Four-eyes means two DIFFERENT eyes."""
    batch = await _pending(db_session, batch_fixture, maker_admin)
    with pytest.raises(SelfApprovalForbidden):
        await approve_batch(
            db_session, batch.id, batch_fixture.tenant.id, admin=maker_admin
        )


@pytest.mark.asyncio
async def test_disbursement_moves_commission_to_the_main_wallet(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """The whole point: held commission becomes spendable, exactly once."""
    commission_before, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )
    main_before, _ = await derive_balance(db_session, batch_fixture.agent_main_wallet.id)

    batch = await _pending(db_session, batch_fixture, maker_admin)
    batch = await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )

    assert batch.status == BATCH_STATUS_APPLIED
    commission_after, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )
    main_after, _ = await derive_balance(db_session, batch_fixture.agent_main_wallet.id)

    moved = commission_before - commission_after
    assert moved == Decimal("40")
    assert main_after - main_before == moved


@pytest.mark.asyncio
async def test_withdrawal_moves_commission_to_the_bank_mirror(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """A clawback takes the money OUT to the operator, not to the user."""
    mirror_before, _ = await derive_balance(db_session, batch_fixture.bank_mirror.id)
    main_before, _ = await derive_balance(db_session, batch_fixture.agent_main_wallet.id)

    batch = await _pending(
        db_session, batch_fixture, maker_admin, batch_type=BATCH_TYPE_WITHDRAWAL
    )
    await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )

    mirror_after, _ = await derive_balance(db_session, batch_fixture.bank_mirror.id)
    main_after, _ = await derive_balance(db_session, batch_fixture.agent_main_wallet.id)

    assert mirror_after - mirror_before == Decimal("40")
    # The user's spendable wallet is untouched — this is a clawback, not a payout.
    assert main_after == main_before


@pytest.mark.asyncio
async def test_posted_rows_carry_their_transaction_id(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """Each row is traceable to the ledger transaction it produced."""
    batch = await _pending(db_session, batch_fixture, maker_admin)
    await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )
    posted = [r for r in await _rows(db_session, batch.id) if r.status == ROW_STATUS_POSTED]
    assert posted
    assert all(r.transaction_id is not None for r in posted)


@pytest.mark.asyncio
async def test_balance_drift_between_approval_and_apply_yields_partial(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """The snapshot is a decision aid, not a guarantee — apply re-checks."""
    batch = await _pending(db_session, batch_fixture, maker_admin)
    await batch_fixture.drain_commission_wallet()

    batch = await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )

    assert batch.status == BATCH_STATUS_APPLIED_PARTIAL
    failed = [r for r in await _rows(db_session, batch.id) if r.status == ROW_STATUS_FAILED]
    assert failed
    assert failed[0].failure_reason == "insufficient_commission_balance"


@pytest.mark.asyncio
async def test_rejection_is_terminal(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """No revise-in-place loop (D16) — the maker uploads a fresh batch."""
    batch = await _pending(db_session, batch_fixture, maker_admin)
    batch = await reject_batch(
        db_session,
        batch.id,
        batch_fixture.tenant.id,
        admin=checker_principal,
        comment="Totals do not match the November statement",
    )
    assert batch.status == BATCH_STATUS_REJECTED

    with pytest.raises(BatchInvalidState):
        await approve_batch(
            db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
        )


@pytest.mark.asyncio
async def test_rejection_requires_a_comment(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """A rejection with no reason gives the maker nothing to correct."""
    batch = await _pending(db_session, batch_fixture, maker_admin)
    with pytest.raises(AppHTTPException) as exc:
        await reject_batch(
            db_session,
            batch.id,
            batch_fixture.tenant.id,
            admin=checker_principal,
            comment="   ",
        )
    assert exc.value.error_code == "reject_comment_required"


@pytest.mark.asyncio
async def test_rejected_batch_moves_no_money(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """Rejection must not post anything."""
    before, _ = await derive_balance(db_session, batch_fixture.agent_commission_wallet.id)
    batch = await _pending(db_session, batch_fixture, maker_admin)
    await reject_batch(
        db_session,
        batch.id,
        batch_fixture.tenant.id,
        admin=checker_principal,
        comment="Not this month",
    )
    after, _ = await derive_balance(db_session, batch_fixture.agent_commission_wallet.id)
    assert after == before


@pytest.mark.asyncio
async def test_six_eyes_needs_two_distinct_approvers(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """One approval is not enough when the tenant policy requires two."""
    db_session.add(
        ApprovalPolicy(
            tenant_id=batch_fixture.tenant.id,
            operation="commission_disbursement",
            required_approvals=2,
        )
    )
    await db_session.commit()

    batch = await _pending(db_session, batch_fixture, maker_admin)
    assert batch.required_approvals == 2

    batch = await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )
    assert batch.status != BATCH_STATUS_APPLIED

    with pytest.raises(BatchDuplicateApprover):
        await approve_batch(
            db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
        )


@pytest.mark.asyncio
async def test_reapplying_is_a_no_op(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """A retried apply must never double-pay (idempotency per batch+row)."""
    batch = await _pending(db_session, batch_fixture, maker_admin)
    batch = await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )
    after_first, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )

    await apply_batch(db_session, batch)
    await db_session.commit()

    after_second, _ = await derive_balance(
        db_session, batch_fixture.agent_commission_wallet.id
    )
    assert after_second == after_first


@pytest.mark.asyncio
async def test_disbursed_total_reconciles_to_the_ledger(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin, checker_principal
) -> None:
    """The statement is DERIVED, never a second source of truth about money."""
    wallet_id = batch_fixture.agent_commission_wallet.id

    async def net() -> Decimal:
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
            ).where(LedgerEntry.account_id == wallet_id)
        )
        return Decimal(str(result.scalar_one()))

    before = await net()
    batch = await _pending(db_session, batch_fixture, maker_admin)
    batch = await approve_batch(
        db_session, batch.id, batch_fixture.tenant.id, admin=checker_principal
    )
    after = await net()

    assert before - after == Decimal(str(batch.amount_total))
