"""The parent leg balances, on both tax axes (spec §7.3, D11).

The whole entries list must sum to zero — that is what post_transaction's
balance assertion enforces, and a three-commission-leg transaction is where an
off-by-one in the tax split would first show up.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.ledger import LedgerEntryRequest
from app.modules.pricing.assembler import (
    ChargeAccounts,
    ChargeAmounts,
    ChargeFlags,
    assemble_charges,
)
from app.shared.models import ENTRY_CREDIT

_ZERO = Decimal("0")


def _accounts(parent_account_id: UUID | None = None) -> ChargeAccounts:
    """Distinct ids for every leg so credits can be attributed per account."""
    return ChargeAccounts(
        payer_account_id=uuid4(),
        beneficiary_account_id=uuid4(),
        fee_account_id=uuid4(),
        service_tax_account_id=uuid4(),
        commission_tax_account_id=uuid4(),
        commission_pool_account_id=uuid4(),
        agent_account_id=uuid4(),
        parent_account_id=parent_account_id,
    )


def _amounts(**overrides: Decimal) -> ChargeAmounts:
    """A cash-in with a R10 child and R5 parent commission, both taxed at 15%."""
    base = {
        "principal": Decimal("1000"),
        "fee": Decimal("10"),
        "commission": Decimal("10"),
        "fee_tax": _ZERO,
        "commission_tax": Decimal("1.5"),
        "parent_commission": Decimal("5"),
        "parent_commission_tax": Decimal("0.75"),
    }
    base.update(overrides)
    return ChargeAmounts(**base)


def _net(entries: list[LedgerEntryRequest]) -> Decimal:
    """Signed sum of every leg — must be zero for a balanced transaction."""
    total = _ZERO
    for entry in entries:
        total += entry.amount if entry.entry_type == ENTRY_CREDIT else -entry.amount
    return total


def _credited_to(entries: list[LedgerEntryRequest], account_id: UUID) -> Decimal:
    """Total credited to one account across all legs."""
    return sum(
        (e.amount for e in entries if e.account_id == account_id and e.entry_type == ENTRY_CREDIT),
        _ZERO,
    )


def test_parent_leg_balances_exclusive_tax() -> None:
    """Exclusive: the pool funds the tax on top, so the parent nets the full 5."""
    parent_account_id = uuid4()
    result = assemble_charges(
        _accounts(parent_account_id), _amounts(), ChargeFlags(commission_tax_inclusive=False)
    )

    assert _net(result.entries) == _ZERO
    assert _credited_to(result.entries, parent_account_id) == Decimal("5")
    assert result.parent_commission_amount == Decimal("5")
    assert result.tax_amount == Decimal("2.25")


def test_parent_leg_balances_inclusive_tax() -> None:
    """Inclusive: the tax is carved out of the parent's own 5, netting 4.25."""
    parent_account_id = uuid4()
    result = assemble_charges(
        _accounts(parent_account_id), _amounts(), ChargeFlags(commission_tax_inclusive=True)
    )

    assert _net(result.entries) == _ZERO
    assert _credited_to(result.entries, parent_account_id) == Decimal("4.25")


def test_no_parent_emits_no_parent_leg() -> None:
    """A standalone agent's transaction keeps the old two-leg commission shape."""
    result = assemble_charges(
        _accounts(parent_account_id=None),
        _amounts(parent_commission=_ZERO, parent_commission_tax=_ZERO),
        ChargeFlags(commission_tax_inclusive=False),
    )

    assert _net(result.entries) == _ZERO
    assert result.parent_commission_amount == _ZERO
    assert result.tax_amount == Decimal("1.5")


def test_skipped_parent_does_not_report_an_amount() -> None:
    """A caller passing an amount with no account must not inflate the totals.

    This is the honesty guard: the assembler zeroes the reported parent amount
    and its tax when no leg was actually emitted, so `parent_commission_amount`
    on the transaction row can never claim money that never moved.
    """
    result = assemble_charges(
        _accounts(parent_account_id=None), _amounts(), ChargeFlags()
    )

    assert _net(result.entries) == _ZERO
    assert result.parent_commission_amount == _ZERO
    assert result.tax_amount == Decimal("1.5")


def test_zero_parent_commission_with_an_account_emits_nothing() -> None:
    """A resolved parent with a zero rate produces no leg."""
    parent_account_id = uuid4()
    result = assemble_charges(
        _accounts(parent_account_id),
        _amounts(parent_commission=_ZERO, parent_commission_tax=_ZERO),
        ChargeFlags(),
    )

    assert _net(result.entries) == _ZERO
    assert _credited_to(result.entries, parent_account_id) == _ZERO
    assert result.parent_commission_amount == _ZERO
