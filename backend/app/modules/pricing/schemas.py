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


class FeeQuoteRequest(BaseModel):
    """User-facing request to preview the service charge for ANY service.

    Service-agnostic by design: `service` is the service code, which is the
    same value as `transaction_type` — the shared lookup key across
    pricing_configs, rules, and transactions. Adding a new user service
    (cash-in, airtime, redemption, ...) needs no new endpoint; the client
    just passes that service's code here.

    `account_type` is optional: when omitted it is derived from `currency`
    (points instruments settle on the points account, everything else on the
    financial wallet), which covers every current service. Pass it explicitly
    only to override that default.
    """

    service: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    account_type: str | None = Field(default=None, max_length=30)


class FeeQuoteResponse(BaseModel):
    """Computed service charge for one service + amount (no ledger write).

    Attributes:
        service: Echoes the requested service code.
        amount: The amount the operation would move (echoes the request).
        fee: Service charge the user would pay on top (Pay-PRD-0260). Zero
            when no pricing config applies to the tuple.
        total: `amount + fee` — what would leave the user's account.
        currency: 3-letter ISO 4217 (uppercase).
    """

    service: str
    amount: Decimal
    fee: Decimal
    total: Decimal
    currency: str
