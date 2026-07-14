"""Charge assembler — the inclusive/exclusive matrix → balanced ledger legs.

Pricing v2 Epic 20 (Story 20.1). One pure function, `assemble_charges`, turns a
principal move plus the computed fee / commission / tax and the three
inclusive/exclusive flags into a fully-balanced `entries` list, so every money
path (cash-in today; p2p / airtime later) shares one tested implementation of
the matrix rather than hand-rolling leg math.

The three axes (design spec §money model):
  1. `fee_inclusive`      — is the fee carved out of the principal (inclusive)
                            or added on top (exclusive)?
  2. `fee_tax_inclusive`  — is the fee's tax carved out of the fee (inclusive)
                            or added on top (exclusive)?
  3. `commission_tax_inclusive` — is the commission's tax carved out of the
                            commission (inclusive) or added on top (exclusive)?

Commission is ALWAYS additive: `DEBIT commission_pool → CREDIT agent` (± its
tax split). The assembler is pure (no DB) so the whole matrix is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.ledger import LedgerEntryRequest
from app.shared.models import ENTRY_CREDIT, ENTRY_DEBIT

_ZERO = Decimal("0")


@dataclass(frozen=True)
class ChargeAccounts:
    """The accounts each charge leg touches.

    Attributes:
        payer_account_id: Principal source (e.g. the agent's e-float) — DEBIT.
        beneficiary_account_id: Principal destination (customer wallet) — CREDIT.
        fee_account_id: `system_fee_collected` — CREDIT of the net fee.
        taxes_account_id: `taxes` wallet — CREDIT of every tax leg.
        commission_pool_account_id: `commission` pool — DEBIT of the payout.
        agent_account_id: The acting agent's wallet — CREDIT of the net commission.
    """

    payer_account_id: UUID
    beneficiary_account_id: UUID
    fee_account_id: UUID
    taxes_account_id: UUID
    commission_pool_account_id: UUID
    agent_account_id: UUID


@dataclass(frozen=True)
class ChargeAmounts:
    """The computed charge amounts (all non-negative).

    Attributes:
        principal: `A` — the amount being moved to the beneficiary.
        fee: `F` — the service fee (slab pricing).
        commission: `C` — the agent's commission (additive from the pool).
        fee_tax: `Tf` — tax on the fee.
        commission_tax: `Tc` — tax on the commission.
    """

    principal: Decimal
    fee: Decimal = _ZERO
    commission: Decimal = _ZERO
    fee_tax: Decimal = _ZERO
    commission_tax: Decimal = _ZERO


@dataclass(frozen=True)
class ChargeFlags:
    """The three inclusive/exclusive axes (all default exclusive)."""

    fee_inclusive: bool = False
    fee_tax_inclusive: bool = False
    commission_tax_inclusive: bool = False


@dataclass(frozen=True)
class AssembledCharges:
    """The output of `assemble_charges`.

    Attributes:
        entries: A balanced list of `LedgerEntryRequest` (ΣDEBIT == ΣCREDIT),
            with every zero-amount leg omitted (the ledger forbids amount == 0).
        fee_amount: `F` — for the transaction's display column.
        commission_amount: `C` — for the transaction's display column.
        tax_amount: `Tf + Tc` — for the transaction's display column.
    """

    entries: list[LedgerEntryRequest]
    fee_amount: Decimal
    commission_amount: Decimal
    tax_amount: Decimal


def _append_if_positive(
    entries: list[LedgerEntryRequest], account_id: UUID, entry_type: str, amount: Decimal
) -> None:
    """Append a leg only when its amount is strictly positive (ledger CHECK)."""
    if amount > _ZERO:
        entries.append(
            LedgerEntryRequest(account_id=account_id, entry_type=entry_type, amount=amount)
        )


def assemble_charges(
    accounts: ChargeAccounts, amounts: ChargeAmounts, flags: ChargeFlags
) -> AssembledCharges:
    """Build the balanced ledger legs for a principal move plus fee/commission/tax.

    Every economic pair balances independently, so the whole `entries` list sums
    to zero (all `_assert_balanced` requires). See the design spec's worked
    example — this function reproduces it byte-for-byte.

    Args:
        accounts: The accounts each leg touches.
        amounts: The computed `A / F / C / Tf / Tc`.
        flags: The three inclusive/exclusive axes.

    Returns:
        An `AssembledCharges` with the balanced legs and the display totals.
    """
    a = amounts.principal
    f = amounts.fee
    c = amounts.commission
    tf = amounts.fee_tax
    tc = amounts.commission_tax

    entries: list[LedgerEntryRequest] = []

    # --- Principal + fee + fee-tax (axes 1 & 2) ------------------------------
    # `fee_tax_on_top` is the fee-tax charged as extra money (exclusive); when
    # inclusive it instead comes out of the fee. Either way Tf reaches taxes.
    fee_tax_on_top = _ZERO if flags.fee_tax_inclusive else tf
    fee_net = f - (tf if flags.fee_tax_inclusive else _ZERO)  # platform's keep

    if flags.fee_inclusive:
        # Payer pays exactly A; the fee (+ any on-top fee-tax) is carved from
        # the beneficiary's credit.
        payer_debit = a
        beneficiary_credit = a - f - fee_tax_on_top
    else:
        # Fee (+ any on-top fee-tax) is added on top of A; beneficiary gets A.
        payer_debit = a + f + fee_tax_on_top
        beneficiary_credit = a

    _append_if_positive(entries, accounts.payer_account_id, ENTRY_DEBIT, payer_debit)
    _append_if_positive(entries, accounts.beneficiary_account_id, ENTRY_CREDIT, beneficiary_credit)
    _append_if_positive(entries, accounts.fee_account_id, ENTRY_CREDIT, fee_net)
    _append_if_positive(entries, accounts.taxes_account_id, ENTRY_CREDIT, tf)

    # --- Commission + commission-tax (axis 3) --------------------------------
    # Always additive: DEBIT the pool, CREDIT the agent (net of inclusive tax).
    comm_tax_on_top = _ZERO if flags.commission_tax_inclusive else tc
    pool_debit = c + comm_tax_on_top
    agent_credit = c - (tc if flags.commission_tax_inclusive else _ZERO)

    _append_if_positive(entries, accounts.commission_pool_account_id, ENTRY_DEBIT, pool_debit)
    _append_if_positive(entries, accounts.agent_account_id, ENTRY_CREDIT, agent_credit)
    _append_if_positive(entries, accounts.taxes_account_id, ENTRY_CREDIT, tc)

    return AssembledCharges(
        entries=entries,
        fee_amount=f,
        commission_amount=c,
        tax_amount=tf + tc,
    )
