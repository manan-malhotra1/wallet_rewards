"""Pydantic v2 schemas for the limits module (Phase G.2)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LimitConfigCreateRequest(BaseModel):
    """Admin payload for creating a limit config.

    All four caps (min/max/daily_count/daily_value) are optional but at
    least one MUST be set — a row with every field NULL is a no-op
    config that we reject at parse time.
    """

    tenant_id: UUID
    transaction_type: str = Field(min_length=1, max_length=50)
    account_type: str = Field(min_length=1, max_length=30)
    currency: str = Field(min_length=3, max_length=3)
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    daily_count_cap: int | None = Field(default=None, gt=0)
    daily_value_cap: Decimal | None = None

    @model_validator(mode="after")
    def _at_least_one_cap(self) -> "LimitConfigCreateRequest":
        """Reject configs that don't limit anything."""
        if (
            self.min_amount is None
            and self.max_amount is None
            and self.daily_count_cap is None
            and self.daily_value_cap is None
        ):
            raise ValueError(
                "At least one of min_amount, max_amount, daily_count_cap, or "
                "daily_value_cap must be set."
            )
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
    min_amount: Decimal | None
    max_amount: Decimal | None
    daily_count_cap: int | None
    daily_value_cap: Decimal | None
    created_at: datetime
    updated_at: datetime
