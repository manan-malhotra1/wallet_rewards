"""Pydantic v2 schemas for the limits module (Phase G.2)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.identity.schemas import UserType


class LimitConfigCreateRequest(BaseModel):
    """Admin payload for creating a service-wise limit config.

    Per-transaction min/max plus rolling count + value caps over
    daily/weekly/monthly windows. Every cap is optional but at least one
    MUST be set — a row with every field NULL is a no-op config that we
    reject at parse time.
    """

    tenant_id: UUID
    transaction_type: str = Field(min_length=1, max_length=50)
    account_type: str = Field(min_length=1, max_length=30)
    currency: str = Field(min_length=2, max_length=10)
    # Type-aware scope (Epic 15): None = default config for all user types.
    user_type: UserType | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    daily_count_cap: int | None = Field(default=None, gt=0)
    daily_value_cap: Decimal | None = None
    weekly_count_cap: int | None = Field(default=None, gt=0)
    weekly_value_cap: Decimal | None = None
    monthly_count_cap: int | None = Field(default=None, gt=0)
    monthly_value_cap: Decimal | None = None

    @model_validator(mode="after")
    def _at_least_one_cap(self) -> "LimitConfigCreateRequest":
        """Reject configs that don't limit anything."""
        caps = (
            self.min_amount,
            self.max_amount,
            self.daily_count_cap,
            self.daily_value_cap,
            self.weekly_count_cap,
            self.weekly_value_cap,
            self.monthly_count_cap,
            self.monthly_value_cap,
        )
        if all(c is None for c in caps):
            raise ValueError("At least one cap must be set.")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot exceed max_amount.")
        return self


class LimitConfigOut(BaseModel):
    """Limit config resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    transaction_type: str
    account_type: str
    currency: str
    user_type: str | None
    min_amount: Decimal | None
    max_amount: Decimal | None
    daily_count_cap: int | None
    daily_value_cap: Decimal | None
    weekly_count_cap: int | None
    weekly_value_cap: Decimal | None
    monthly_count_cap: int | None
    monthly_value_cap: Decimal | None
    created_at: datetime
    updated_at: datetime


# Wallet-level limit config columns (max_balance + send/receive caps across
# daily/weekly/monthly windows). Listed once so the create-request and the
# response schema stay in lockstep.
_WALLET_CAP_FIELDS = (
    "send_daily_count_cap",
    "send_weekly_count_cap",
    "send_monthly_count_cap",
    "receive_daily_count_cap",
    "receive_weekly_count_cap",
    "receive_monthly_count_cap",
)
_WALLET_VALUE_FIELDS = (
    "send_daily_value_cap",
    "send_weekly_value_cap",
    "send_monthly_value_cap",
    "receive_daily_value_cap",
    "receive_weekly_value_cap",
    "receive_monthly_value_cap",
)


class WalletLimitConfigCreateRequest(BaseModel):
    """Admin payload for a per-(tenant, currency) financial-wallet limit config.

    A max-balance ceiling plus cumulative send + receive count/value caps over
    rolling daily/weekly/monthly windows. Every cap is optional but at least
    one MUST be set. Count caps and max_balance must be positive; value caps
    non-negative.
    """

    tenant_id: UUID
    currency: str = Field(min_length=2, max_length=10)
    user_type: UserType | None = None
    max_balance: Decimal | None = Field(default=None, gt=Decimal("0"))

    send_daily_count_cap: int | None = Field(default=None, gt=0)
    send_daily_value_cap: Decimal | None = Field(default=None, ge=Decimal("0"))
    send_weekly_count_cap: int | None = Field(default=None, gt=0)
    send_weekly_value_cap: Decimal | None = Field(default=None, ge=Decimal("0"))
    send_monthly_count_cap: int | None = Field(default=None, gt=0)
    send_monthly_value_cap: Decimal | None = Field(default=None, ge=Decimal("0"))

    receive_daily_count_cap: int | None = Field(default=None, gt=0)
    receive_daily_value_cap: Decimal | None = Field(default=None, ge=Decimal("0"))
    receive_weekly_count_cap: int | None = Field(default=None, gt=0)
    receive_weekly_value_cap: Decimal | None = Field(default=None, ge=Decimal("0"))
    receive_monthly_count_cap: int | None = Field(default=None, gt=0)
    receive_monthly_value_cap: Decimal | None = Field(default=None, ge=Decimal("0"))

    @model_validator(mode="after")
    def _at_least_one_cap(self) -> "WalletLimitConfigCreateRequest":
        """Reject a config that limits nothing."""
        fields = ("max_balance", *_WALLET_CAP_FIELDS, *_WALLET_VALUE_FIELDS)
        if all(getattr(self, f) is None for f in fields):
            raise ValueError("At least one cap (or max_balance) must be set.")
        return self


class WalletLimitConfigOut(BaseModel):
    """Wallet limit config resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    currency: str
    user_type: str | None
    max_balance: Decimal | None
    send_daily_count_cap: int | None
    send_daily_value_cap: Decimal | None
    send_weekly_count_cap: int | None
    send_weekly_value_cap: Decimal | None
    send_monthly_count_cap: int | None
    send_monthly_value_cap: Decimal | None
    receive_daily_count_cap: int | None
    receive_daily_value_cap: Decimal | None
    receive_weekly_count_cap: int | None
    receive_weekly_value_cap: Decimal | None
    receive_monthly_count_cap: int | None
    receive_monthly_value_cap: Decimal | None
    created_at: datetime
    updated_at: datetime
