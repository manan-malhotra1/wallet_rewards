"""Pass-1 validation: every reject reason in spec §8.2, plus the happy path.

The checker must only ever see valid rows, so every one of these fires at
UPLOAD, before the batch reaches an approver.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commission_batches.csv_io import ParsedRow
from app.modules.commission_batches.validation import validate_rows
from tests.commission_batches.conftest import BatchFixture


def _row(n: int, msisdn: str, currency: str = "ZAR", amount: str | None = "10") -> ParsedRow:
    """One parsed row with sensible defaults."""
    return ParsedRow(
        row_number=n,
        msisdn=msisdn,
        currency=currency,
        amount=Decimal(amount) if amount is not None else None,
        note=None,
    )


async def _validate(db_session: AsyncSession, fx: BatchFixture, rows: list[ParsedRow]):
    """Run validation in the fixture's tenant."""
    return await validate_rows(db_session, tenant_id=fx.tenant.id, rows=rows)


@pytest.mark.asyncio
async def test_valid_row_resolves_with_a_balance_snapshot(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A payable row carries the wallet, the balance and the read time."""
    results = await _validate(
        db_session, batch_fixture, [_row(1, batch_fixture.agent_msisdn, amount="50")]
    )
    assert results[0].failure_reason is None
    assert results[0].resolved_account_id == batch_fixture.agent_commission_wallet.id
    assert results[0].balance_snapshot == Decimal("100")
    assert results[0].snapshot_at is not None


@pytest.mark.asyncio
async def test_unknown_msisdn(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A phone that resolves to nobody in this tenant."""
    results = await _validate(db_session, batch_fixture, [_row(1, "+27000000000")])
    assert results[0].failure_reason == "msisdn_not_found"


@pytest.mark.asyncio
async def test_consumer_is_not_eligible(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """Consumers never hold a commission wallet (D4)."""
    results = await _validate(
        db_session, batch_fixture, [_row(1, batch_fixture.consumer_msisdn)]
    )
    assert results[0].failure_reason == "user_not_eligible"


@pytest.mark.asyncio
async def test_unknown_currency(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A currency with no live financial instrument in this tenant."""
    results = await _validate(
        db_session, batch_fixture, [_row(1, batch_fixture.agent_msisdn, currency="XXX")]
    )
    assert results[0].failure_reason == "unknown_currency"


@pytest.mark.asyncio
async def test_amount_over_balance(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """You cannot disburse more than the agent accrued."""
    results = await _validate(
        db_session, batch_fixture, [_row(1, batch_fixture.agent_msisdn, amount="1000")]
    )
    assert results[0].failure_reason == "insufficient_commission_balance"


@pytest.mark.asyncio
async def test_amount_exactly_equal_to_balance_is_valid(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """Draining the wallet to zero is legitimate — the floor is >= 0."""
    results = await _validate(
        db_session, batch_fixture, [_row(1, batch_fixture.agent_msisdn, amount="100")]
    )
    assert results[0].failure_reason is None


@pytest.mark.asyncio
async def test_zero_and_negative_amounts(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """Neither moves money; both are the maker's error."""
    results = await _validate(
        db_session,
        batch_fixture,
        [
            _row(1, batch_fixture.agent_msisdn, amount="0"),
            _row(2, batch_fixture.agent_msisdn, amount="-5"),
        ],
    )
    assert results[0].failure_reason == "invalid_amount"
    assert results[1].failure_reason == "invalid_amount"


@pytest.mark.asyncio
async def test_unparseable_amount(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A None amount from the parser rejects rather than crashing."""
    results = await _validate(
        db_session, batch_fixture, [_row(1, batch_fixture.agent_msisdn, amount=None)]
    )
    assert results[0].failure_reason == "invalid_amount"


@pytest.mark.asyncio
async def test_duplicate_msisdn_currency_within_the_file(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """The FIRST occurrence is kept; later ones reject, so runs are deterministic."""
    results = await _validate(
        db_session,
        batch_fixture,
        [
            _row(1, batch_fixture.agent_msisdn, amount="10"),
            _row(2, batch_fixture.agent_msisdn, amount="20"),
        ],
    )
    assert results[0].failure_reason is None
    assert results[1].failure_reason == "duplicate_row"


@pytest.mark.asyncio
async def test_same_msisdn_different_currency_is_not_a_duplicate(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A user may legitimately be paid from two commission wallets in one run."""
    results = await _validate(
        db_session,
        batch_fixture,
        [
            _row(1, batch_fixture.agent_msisdn, currency="ZAR", amount="10"),
            _row(2, batch_fixture.agent_msisdn, currency="INR", amount="10"),
        ],
    )
    assert results[0].failure_reason is None
    assert results[1].failure_reason != "duplicate_row"


@pytest.mark.asyncio
async def test_results_preserve_input_order(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """Callers rely on positional correspondence to build the rejects file."""
    rows = [
        _row(1, "+27000000000"),
        _row(2, batch_fixture.agent_msisdn, amount="10"),
        _row(3, batch_fixture.consumer_msisdn),
    ]
    results = await _validate(db_session, batch_fixture, rows)
    assert [r.parsed.row_number for r in results] == [1, 2, 3]
    assert results[0].failure_reason == "msisdn_not_found"
    assert results[1].failure_reason is None
    assert results[2].failure_reason == "user_not_eligible"
