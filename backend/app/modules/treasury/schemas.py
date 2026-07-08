"""Pydantic v2 schemas for the treasury module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Identifier types accepted by Fund and Withdraw — operators never type
# a raw UUID. Mirrors the UserIdentifier model's enum.
TreasuryIdentifierType = Literal["phone", "email", "account_number", "card_number"]


class SystemWalletOut(BaseModel):
    """A system-owned account (user_id IS NULL) with its derived balance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    account_type: str
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
    transaction_type: str
    status: str
    entry_type: str  # "DEBIT" | "CREDIT"
    entry_amount: Decimal
    currency: str
    created_at: datetime


class FundUserRequest(BaseModel):
    """Admin top-up payload — credits a user wallet from `system_cash_inflow`.

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
    """Result of an admin top-up."""

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
    """

    tenant_id: UUID
    identifier_type: TreasuryIdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=2, max_length=10)
    reason: str = Field(min_length=1, max_length=500)


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
    reason: str = Field(min_length=1, max_length=500)


class AdjustSystemWalletResponse(BaseModel):
    """Result of a system-wallet adjustment."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    account_id: UUID
    amount: Decimal  # signed
    currency: str
    new_balance: Decimal
