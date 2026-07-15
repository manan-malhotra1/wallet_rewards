"""Pydantic v2 schemas for the treasury module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Identifier types accepted by Fund and Withdraw — operators never type
# a raw UUID. Mirrors the UserIdentifier model's enum.
TreasuryIdentifierType = Literal["phone", "email", "account_number", "card_number"]


class SystemWalletOut(BaseModel):
    """A system-owned account (user_id IS NULL) with its derived balance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    account_type: str
    # Bank mirrors (operator_adjustment) carry a name so the UI can list each
    # one separately; NULL for every other system account type.
    name: str | None = None
    currency: str
    status: str
    balance: Decimal
    created_at: datetime


class SystemWalletTransactionOut(BaseModel):
    """A transaction touching a system wallet, surfaced for the drill-down.

    `entry_amount` is the amount on the leg that touched this account.
    `entry_type` says whether the system account was DEBITed or CREDITed
    in this transaction (i.e. did its balance go up or down).
    """

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    # Customer-facing reference `S_<YYYYMMDDHHMMSS><NNNNNN>` for the parent txn.
    reference: str | None = None
    transaction_type: str
    status: str
    entry_type: str  # "DEBIT" | "CREDIT"
    entry_amount: Decimal
    currency: str
    created_at: datetime


class FundUserRequest(BaseModel):
    """Admin fund payload — credits a user wallet from `system_cash_inflow`.

    The user is identified by a registered identifier (phone, email,
    account or card) rather than a raw UUID — operators don't have
    UUIDs to hand at the counter.
    """

    tenant_id: UUID
    identifier_type: TreasuryIdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=2, max_length=10)
    reason: str = Field(min_length=1, max_length=500)


class FundUserResponse(BaseModel):
    """Result of an admin fund."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    user_id: UUID
    amount: Decimal
    currency: str
    new_balance: Decimal


class WithdrawFromUserRequest(BaseModel):
    """Admin withdraw payload — debits a user wallet and credits operator_adjustment.

    Identified the same way as fund — by registered identifier, not UUID.
    Admin operations are PIN-less and fee-less; operator authentication
    is the Keycloak session.

    Supply exactly one of `amount` or `withdraw_all`. `withdraw_all=true` (with
    no amount) pulls the wallet's full available balance. Both only ever target
    the user's financial_wallet — never a system wallet.
    """

    tenant_id: UUID
    identifier_type: TreasuryIdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    withdraw_all: bool = False
    currency: str = Field(min_length=2, max_length=10)
    # The bank mirror (operator_adjustment) that receives the counter-leg —
    # the operator picks it explicitly; there is no implicit default.
    bank_mirror_account_id: UUID
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _amount_xor_withdraw_all(self) -> Self:
        """Exactly one of amount / withdraw_all must be provided."""
        if self.withdraw_all and self.amount is not None:
            raise ValueError("Provide either amount or withdraw_all, not both.")
        if not self.withdraw_all and self.amount is None:
            raise ValueError("amount is required unless withdraw_all is true.")
        return self


class WithdrawFromUserResponse(BaseModel):
    """Result of an admin withdraw."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    user_id: UUID
    amount: Decimal
    currency: str
    new_balance: Decimal


class AdjustSystemWalletRequest(BaseModel):
    """Admin fund/withdraw payload for a system wallet.

    Positive `amount` = fund (operator deposit). Negative = withdraw
    (operator cash-out). `reason` is required for the audit row.
    """

    tenant_id: UUID
    account_id: UUID
    amount: Decimal  # signed
    # The bank mirror (operator_adjustment) used as the counter-leg — the
    # operator picks it explicitly; there is no implicit default.
    bank_mirror_account_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class AdjustSystemWalletResponse(BaseModel):
    """Result of a system-wallet adjustment."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    account_id: UUID
    amount: Decimal  # signed
    currency: str
    new_balance: Decimal


class CreateBankMirrorRequest(BaseModel):
    """Create a new named bank mirror (operator_adjustment) for a currency.

    Names are unique per (tenant, currency); a duplicate is rejected 409.
    """

    currency: str = Field(min_length=2, max_length=10)
    name: str = Field(min_length=1, max_length=100)


class RenameBankMirrorRequest(BaseModel):
    """Rename an existing bank mirror. New name must be unique in its scope."""

    name: str = Field(min_length=1, max_length=100)
