"""Charge-assembler tests (Story 20.1).

The assembler is a pure function, so these run without a DB. They prove:
  - the design spec's worked example is reproduced byte-for-byte;
  - ΣDEBIT == ΣCREDIT for EVERY combination of the three inclusive/exclusive
    flags (the parametrized matrix);
  - zero commission/tax collapses to the plain principal + fee legs.
"""

from __future__ import annotations

import itertools
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.pricing.assembler import (
    ChargeAccounts,
    ChargeAmounts,
    ChargeFlags,
    assemble_charges,
)
from app.shared.models import ENTRY_CREDIT, ENTRY_DEBIT

# Stable fake account ids — the assembler never touches a DB.
PAYER = uuid4()
BENEFICIARY = uuid4()
FEE = uuid4()
SERVICE_TAX = uuid4()
COMMISSION_TAX = uuid4()
POOL = uuid4()
AGENT = uuid4()

ACCOUNTS = ChargeAccounts(
    payer_account_id=PAYER,
    beneficiary_account_id=BENEFICIARY,
    fee_account_id=FEE,
    service_tax_account_id=SERVICE_TAX,
    commission_tax_account_id=COMMISSION_TAX,
    commission_pool_account_id=POOL,
    agent_account_id=AGENT,
)


def _sum(entries, entry_type: str) -> Decimal:
    return sum((e.amount for e in entries if e.entry_type == entry_type), start=Decimal("0"))


def _credit_to(entries, account_id) -> Decimal:
    return sum(
        (e.amount for e in entries if e.account_id == account_id and e.entry_type == ENTRY_CREDIT),
        start=Decimal("0"),
    )


def _debit_to(entries, account_id) -> Decimal:
    return sum(
        (e.amount for e in entries if e.account_id == account_id and e.entry_type == ENTRY_DEBIT),
        start=Decimal("0"),
    )


def test_worked_example_byte_for_byte() -> None:
    """The design spec's worked cash-in reproduces exactly.

    A=100, F=2, Tf=0.30, C=1, Tc=0.15; fee inclusive, fee-tax exclusive,
    commission-tax inclusive. Expected legs:
        DEBIT  payer        100.00
        CREDIT beneficiary   97.70   (A - F - Tf)
        CREDIT fee            2.00   (F)
        CREDIT service-tax    0.30   (Tf)
        DEBIT  pool           1.00   (C)
        CREDIT agent          0.85   (C - Tc)
        CREDIT commission-tax 0.15   (Tc)
    """
    result = assemble_charges(
        ACCOUNTS,
        ChargeAmounts(
            principal=Decimal("100"),
            fee=Decimal("2"),
            commission=Decimal("1"),
            fee_tax=Decimal("0.30"),
            commission_tax=Decimal("0.15"),
        ),
        ChargeFlags(
            fee_inclusive=True,
            fee_tax_inclusive=False,
            commission_tax_inclusive=True,
        ),
    )
    entries = result.entries

    assert _debit_to(entries, PAYER) == Decimal("100")
    assert _credit_to(entries, BENEFICIARY) == Decimal("97.70")
    assert _credit_to(entries, FEE) == Decimal("2")
    assert _credit_to(entries, SERVICE_TAX) == Decimal("0.30")  # Tf
    assert _credit_to(entries, COMMISSION_TAX) == Decimal("0.15")  # Tc
    assert _debit_to(entries, POOL) == Decimal("1")
    assert _credit_to(entries, AGENT) == Decimal("0.85")

    # Balanced overall.
    assert _sum(entries, ENTRY_DEBIT) == _sum(entries, ENTRY_CREDIT) == Decimal("101")

    # Display totals.
    assert result.fee_amount == Decimal("2")
    assert result.commission_amount == Decimal("1")
    assert result.tax_amount == Decimal("0.45")


@pytest.mark.parametrize(
    "fee_inclusive,fee_tax_inclusive,commission_tax_inclusive",
    list(itertools.product([False, True], repeat=3)),
)
def test_every_flag_combination_balances(
    fee_inclusive: bool, fee_tax_inclusive: bool, commission_tax_inclusive: bool
) -> None:
    """ΣDEBIT == ΣCREDIT for all 8 flag combinations with non-trivial amounts."""
    result = assemble_charges(
        ACCOUNTS,
        ChargeAmounts(
            principal=Decimal("200"),
            fee=Decimal("5"),
            commission=Decimal("3"),
            fee_tax=Decimal("0.75"),
            commission_tax=Decimal("0.45"),
        ),
        ChargeFlags(
            fee_inclusive=fee_inclusive,
            fee_tax_inclusive=fee_tax_inclusive,
            commission_tax_inclusive=commission_tax_inclusive,
        ),
    )
    assert _sum(result.entries, ENTRY_DEBIT) == _sum(result.entries, ENTRY_CREDIT)
    # Every leg is strictly positive (ledger CHECK).
    assert all(e.amount > Decimal("0") for e in result.entries)
    # Fee-tax and commission-tax land in their own collectors.
    assert _credit_to(result.entries, SERVICE_TAX) == Decimal("0.75")  # Tf
    assert _credit_to(result.entries, COMMISSION_TAX) == Decimal("0.45")  # Tc


def test_zero_commission_and_tax_collapses_to_principal_and_fee() -> None:
    """With C=Tf=Tc=0 and exclusive fee, only the 3 plain fee legs appear."""
    result = assemble_charges(
        ACCOUNTS,
        ChargeAmounts(principal=Decimal("100"), fee=Decimal("2")),
        ChargeFlags(),  # all exclusive
    )
    entries = result.entries
    assert len(entries) == 3
    assert _debit_to(entries, PAYER) == Decimal("102")  # A + F on top
    assert _credit_to(entries, BENEFICIARY) == Decimal("100")
    assert _credit_to(entries, FEE) == Decimal("2")
    assert _credit_to(entries, SERVICE_TAX) == Decimal("0")
    assert _credit_to(entries, COMMISSION_TAX) == Decimal("0")
    assert result.commission_amount == Decimal("0")
    assert result.tax_amount == Decimal("0")


def test_fully_inclusive_fee_that_is_all_tax_omits_zero_fee_leg() -> None:
    """Edge case: F == Tf with fee-tax inclusive → net fee is 0, leg omitted."""
    result = assemble_charges(
        ACCOUNTS,
        ChargeAmounts(principal=Decimal("100"), fee=Decimal("1"), fee_tax=Decimal("1")),
        ChargeFlags(fee_inclusive=True, fee_tax_inclusive=True),
    )
    entries = result.entries
    assert _credit_to(entries, FEE) == Decimal("0")  # no fee leg emitted
    assert _credit_to(entries, BENEFICIARY) == Decimal("99")  # A - F
    assert _credit_to(entries, SERVICE_TAX) == Decimal("1")
    assert _sum(entries, ENTRY_DEBIT) == _sum(entries, ENTRY_CREDIT)
