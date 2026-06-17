"""Pydantic v2 schemas for the treasury module."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    """Admin top-up payload — credits a user wallet from `system_cash_inflow`."""

    tenant_id: UUID
    user_id: UUID
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    reason: str = Field(min_length=1, max_length=500)


class FundUserResponse(BaseModel):
    """Result of an admin top-up."""

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
