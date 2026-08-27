"""Pydantic v2 schemas for the commissions module (Pricing v2 Epic 19)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.identity.schemas import UserType


class CommissionConfigCreateRequest(BaseModel):
    """Admin payload to create a commission config.

    A commission is the platform-funded, always-additive payout to the acting
    agent. Zero on both `fixed_commission` and `variable_commission_pct` is a
    valid "no commission" row.
    """

    tenant_id: UUID
    transaction_type: str = Field(min_length=1, max_length=50)
    currency: str = Field(min_length=3, max_length=3)
    # None = default commission for all user types.
    user_type: UserType | None = None
    amount_from: Decimal | None = Field(default=None, ge=Decimal("0"))
    amount_to: Decimal | None = Field(default=None, gt=Decimal("0"))
    fixed_commission: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    variable_commission_pct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), lt=Decimal("1"))
    commission_cap: Decimal | None = Field(default=None, gt=Decimal("0"))
    # Where the commission lands (spec 2026-08-26, D6).
    payout_destination: Literal["main_wallet", "commission_wallet"] = "main_wallet"
    # The earner's PARENT is paid from this same row, as a percentage of the
    # TRANSACTION AMOUNT using the same band (spec D8).
    #
    # REQUIRED with no default, deliberately: zero is a decision the operator
    # must make, not an omission. A default here would let a caller ship a rule
    # whose parent leg silently pays nothing when they meant it to pay
    # something, and nothing downstream could tell the two apart.
    #
    # `config_requests/apply.py` re-validates STORED payloads against this
    # schema at APPROVAL time, so payloads written before these fields existed
    # would 422 forever. Migration 0069 backfills every non-terminal commission
    # request's payload with explicit zeros, which is what makes this safe.
    parent_fixed_commission: Decimal = Field(ge=Decimal("0"))
    parent_variable_commission_pct: Decimal = Field(ge=Decimal("0"), lt=Decimal("1"))
    parent_commission_cap: Decimal | None = Field(default=None, gt=Decimal("0"))

    @model_validator(mode="after")
    def _parent_cap_only_with_variable(self) -> CommissionConfigCreateRequest:
        """A parent cap with a zero parent rate is a config the operator got wrong."""
        if (
            self.parent_commission_cap is not None
            and self.parent_variable_commission_pct == 0
        ):
            raise ValueError(
                "parent_commission_cap only makes sense when "
                "parent_variable_commission_pct > 0."
            )
        return self

    @model_validator(mode="after")
    def _cap_only_with_variable(self) -> CommissionConfigCreateRequest:
        if self.commission_cap is not None and self.variable_commission_pct == 0:
            raise ValueError("commission_cap only makes sense when variable_commission_pct > 0.")
        return self

    @model_validator(mode="after")
    def _amount_band_ordered(self) -> CommissionConfigCreateRequest:
        if (
            self.amount_from is not None
            and self.amount_to is not None
            and self.amount_to <= self.amount_from
        ):
            raise ValueError("amount_to must be greater than amount_from.")
        return self


class CommissionConfigOut(BaseModel):
    """Commission config resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    transaction_type: str
    currency: str
    user_type: str | None
    amount_from: Decimal | None
    amount_to: Decimal | None
    fixed_commission: Decimal
    variable_commission_pct: Decimal
    commission_cap: Decimal | None
    created_at: datetime
    updated_at: datetime
