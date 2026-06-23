"""Pydantic v2 schemas for the accounts module."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal[
    "financial_wallet",
    "points_account",
    "system_points_issuance",
    "provider_redemption_wallet",
]


class CreateAccountRequest(BaseModel):
    """Test-only account creation payload.

    Either `user_id` or `merchant_id` is set for user/merchant accounts; both
    omitted for system-owned accounts (`system_points_issuance`,
    `provider_redemption_wallet`).
    """

    tenant_id: UUID
    user_id: UUID | None = None
    merchant_id: UUID | None = None
    account_type: AccountType
    currency: str = Field(min_length=2, max_length=10)


class AccountOut(BaseModel):
    """Account resource returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    merchant_id: UUID | None
    account_type: str
    currency: str
    status: str


class BalanceResponse(BaseModel):
    """Available balance for an account.

    `available = balance - reserved_balance`. Per Pay-PRD-0130, this is the
    figure used for transaction eligibility checks (overdraft prevention).
    """

    account_id: UUID
    balance: Decimal
    reserved_balance: Decimal
    available_balance: Decimal
    currency: str
