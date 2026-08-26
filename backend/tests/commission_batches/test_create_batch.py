"""Batch creation: valid rows staged, bad rows persisted, empty batch refused."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commission_batches.service import (
    create_batch,
    get_batch_rejects_csv,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    BATCH_STATUS_PENDING,
    BATCH_TYPE_DISBURSEMENT,
    BATCH_TYPE_WITHDRAWAL,
    ROW_STATUS_REJECTED,
    ROW_STATUS_VALID,
    CommissionBatchRow,
)
from tests.commission_batches.conftest import BatchFixture


def _csv(*lines: str) -> str:
    """A batch file with the standard header."""
    return "msisdn,currency,amount,note\n" + "".join(f"{line}\n" for line in lines)


async def _rows(session: AsyncSession, batch_id) -> list[CommissionBatchRow]:
    """Every persisted row of a batch."""
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
async def test_mixed_file_stages_valid_rows_only(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """Bad rows are PERSISTED with a reason, not discarded (D15)."""
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=_csv(
            f"{batch_fixture.agent_msisdn},ZAR,50,Verified",
            "+27000000000,ZAR,10,Unknown",
        ),
        admin=maker_admin,
    )

    assert batch.status == BATCH_STATUS_PENDING
    assert batch.row_count_total == 2
    assert batch.row_count_valid == 1

    rows = await _rows(db_session, batch.id)
    by_status = {r.status: r for r in rows}
    assert by_status[ROW_STATUS_VALID].msisdn == batch_fixture.agent_msisdn
    assert by_status[ROW_STATUS_REJECTED].failure_reason == "msisdn_not_found"
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_amount_total_counts_valid_rows_only(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """The header total must match what will actually move."""
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=_csv(
            f"{batch_fixture.agent_msisdn},ZAR,50,",
            "+27000000000,ZAR,999,",
        ),
        admin=maker_admin,
    )
    assert Decimal(str(batch.amount_total)) == Decimal("50")


@pytest.mark.asyncio
async def test_batch_with_no_valid_rows_is_refused(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """Refused outright rather than created empty — nothing for a checker to do."""
    with pytest.raises(AppHTTPException) as exc:
        await create_batch(
            db_session,
            tenant_id=batch_fixture.tenant.id,
            batch_type=BATCH_TYPE_DISBURSEMENT,
            file_name="bad.csv",
            content=_csv("+27000000000,ZAR,10,"),
            admin=maker_admin,
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "batch_no_valid_rows"


@pytest.mark.asyncio
async def test_malformed_file_is_a_clean_422(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """A missing column is a file-level error, not 5000 row rejects."""
    with pytest.raises(AppHTTPException) as exc:
        await create_batch(
            db_session,
            tenant_id=batch_fixture.tenant.id,
            batch_type=BATCH_TYPE_DISBURSEMENT,
            file_name="bad.csv",
            content="msisdn,amount\n27831234567,10\n",
            admin=maker_admin,
        )
    assert exc.value.error_code == "batch_file_invalid"


@pytest.mark.asyncio
async def test_withdrawal_requires_a_bank_mirror(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """A clawback with nowhere to send the money is refused."""
    with pytest.raises(AppHTTPException) as exc:
        await create_batch(
            db_session,
            tenant_id=batch_fixture.tenant.id,
            batch_type=BATCH_TYPE_WITHDRAWAL,
            file_name="claw.csv",
            content=_csv(f"{batch_fixture.agent_msisdn},ZAR,50,"),
            admin=maker_admin,
        )
    assert exc.value.error_code == "bank_mirror_required"


@pytest.mark.asyncio
async def test_withdrawal_accepts_a_valid_mirror(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """The happy path for a clawback batch."""
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_WITHDRAWAL,
        file_name="claw.csv",
        content=_csv(f"{batch_fixture.agent_msisdn},ZAR,50,Incorrectly accrued"),
        admin=maker_admin,
        destination_account_id=batch_fixture.bank_mirror.id,
    )
    assert batch.destination_account_id == batch_fixture.bank_mirror.id
    assert batch.row_count_valid == 1


@pytest.mark.asyncio
async def test_disbursement_ignores_a_supplied_mirror(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """A disbursement's destination is each earner's own main wallet."""
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=_csv(f"{batch_fixture.agent_msisdn},ZAR,50,"),
        admin=maker_admin,
        destination_account_id=batch_fixture.bank_mirror.id,
    )
    assert batch.destination_account_id is None


@pytest.mark.asyncio
async def test_maker_note_is_preserved(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """The note justifies the delta and must reach the checker verbatim."""
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=_csv(f"{batch_fixture.agent_msisdn},ZAR,50,R50 held pending query"),
        admin=maker_admin,
    )
    rows = await _rows(db_session, batch.id)
    assert rows[0].note == "R50 held pending query"


@pytest.mark.asyncio
async def test_rejects_csv_lists_the_bad_rows(
    db_session: AsyncSession, batch_fixture: BatchFixture, maker_admin
) -> None:
    """The maker downloads, fixes, and uploads a NEW batch (D15)."""
    batch = await create_batch(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        batch_type=BATCH_TYPE_DISBURSEMENT,
        file_name="nov.csv",
        content=_csv(
            f"{batch_fixture.agent_msisdn},ZAR,50,",
            "+27000000000,ZAR,10,Unknown",
        ),
        admin=maker_admin,
    )

    body = await get_batch_rejects_csv(db_session, batch.id, batch_fixture.tenant.id)
    assert "msisdn_not_found" in body
    assert "+27000000000" in body
    # The VALID row must not appear — the maker only re-uploads what failed.
    assert batch_fixture.agent_msisdn not in body
