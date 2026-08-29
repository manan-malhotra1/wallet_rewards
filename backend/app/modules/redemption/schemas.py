"""Pydantic v2 schemas for the redemption module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversionRateCreateRequest(BaseModel):
    """Admin payload for a per-(tenant, currency) points→fiat conversion rate.

    Read as "`points_per_unit` PTS = `value_per_unit` `currency`" — e.g.
    100 PTS = 10.00 ZAR. Rides the config change-request maker-checker
    (config_type `conversion_rate`, Pay-PRD-1210). Exactly one rate per
    (tenant, currency); both sides must be positive.
    """

    tenant_id: UUID
    currency: str = Field(min_length=2, max_length=10)
    points_per_unit: Decimal = Field(gt=Decimal("0"))
    value_per_unit: Decimal = Field(gt=Decimal("0"))
    # Anti-drain caps (Pay-PRD-1295): absolute points per redemption and/or a
    # max percentage of the user's current balance. Omitted = uncapped.
    max_points_per_txn: Decimal | None = Field(default=None, gt=Decimal("0"))
    max_balance_pct_per_txn: Decimal | None = Field(
        default=None, gt=Decimal("0"), le=Decimal("100")
    )


class ConversionRateOut(BaseModel):
    """Conversion-rate resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    currency: str
    points_per_unit: Decimal
    value_per_unit: Decimal
    max_points_per_txn: Decimal | None
    max_balance_pct_per_txn: Decimal | None
    status: str
    created_at: datetime
    updated_at: datetime


class InternalRedemptionRequest(BaseModel):
    """User payload for an internal redemption (Pay-PRD-1200, design 07 §6.3).

    `tenant_id` / `user_id` come from the session token. Body carries the
    points to burn and the destination wallet currency; `pin` is required only
    when a step-up policy for ("redemption", "PTS") sets a threshold below
    `points_amount`.
    """

    points_amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=2, max_length=10)
    pin: str | None = Field(default=None, min_length=4, max_length=12)


class InternalRedemptionOut(BaseModel):
    """Internal-redemption receipt — the cross-referenced points/fiat pair."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    points_transaction_id: UUID
    payout_transaction_id: UUID
    currency: str
    points_amount: Decimal
    fiat_amount: Decimal
    points_per_unit: Decimal
    value_per_unit: Decimal
    created_at: datetime
