"""Pydantic v2 schemas for the pricing module (Phase G.3)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PricingConfigCreateRequest(BaseModel):
    """Admin payload to create a fee config.

    `fixed_fee + variable_fee_pct` can be zero on either side — but
    "zero on both" is the explicit "no-fee" config and is permitted
    (operators have to declare it; pricing is never silently skipped).
    """

    tenant_id: UUID
    transaction_type: str = Field(min_length=1, max_length=50)
    account_type: str = Field(min_length=1, max_length=30)
    currency: str = Field(min_length=3, max_length=3)
    fixed_fee: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    variable_fee_pct: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"), lt=Decimal("1")
    )
    fee_cap: Decimal | None = Field(default=None, gt=Decimal("0"))

    @model_validator(mode="after")
    def _fee_cap_only_with_variable(self) -> "PricingConfigCreateRequest":
        if self.fee_cap is not None and self.variable_fee_pct == 0:
            raise ValueError(
                "fee_cap only makes sense when variable_fee_pct > 0."
            )
        return self


class PricingConfigOut(BaseModel):
    """Pricing config resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    transaction_type: str
    account_type: str
    currency: str
    fixed_fee: Decimal
    variable_fee_pct: Decimal
    fee_cap: Decimal | None
    created_at: datetime
    updated_at: datetime


class FeePreviewResponse(BaseModel):
    """Result of `calculate_fee()` exposed for the future user-facing
    "review this transaction" surface. Not used by routers yet."""

    fee: Decimal
    breakdown: dict[str, Decimal]
