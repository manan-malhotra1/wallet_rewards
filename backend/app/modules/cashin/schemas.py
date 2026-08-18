"""Pydantic v2 schemas for the agent cash-in module (Pricing v2 Epic 21).

The agent + tenant come from the session token — never the body. The customer
is named by an identifier (phone/email/account), resolved tenant-scoped.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IdentifierType = Literal["phone", "email", "account_number", "card_number"]


class CustomerIdentifier(BaseModel):
    """How the agent refers to the customer being funded."""

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)


class CashInRequest(BaseModel):
    """Agent cash-in payload (auth-gated).

    `pin` is optional: include it only when a step-up policy requires
    re-verification for the amount/currency.
    """

    customer: CustomerIdentifier
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    # Optional derived service to transact under. Omitted -> plain 'cash_in'
    # (identical to pre-existing behaviour). Resolved ONCE, up front, and used
    # for every downstream permission / pricing / limits / ledger step (spec §7).
    service_code: str | None = Field(default=None, max_length=50)


class CashInResponse(BaseModel):
    """Result of a successful cash-in.

    Attributes:
        transaction_id: The double-entry transaction id.
        status: Lifecycle state ("COMPLETED" on the happy path).
        amount: The principal credited to the customer.
        fee: Service fee charged (slab pricing).
        commission: Commission paid to the acting agent from the pool.
        tax: Total tax collected (on fee + commission).
        currency: 3-letter ISO 4217 (uppercase).
        customer_user_id: The funded customer.
        earned_points: Points the CUSTOMER earned from a reward rule that fired
            on this cash-in (0 outside `both` mode, no matching rule, or replay).
    """

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    # Customer-facing reference `S_<YYYYMMDDHHMMSS><NNNNNN>` for this cash-in.
    reference: str | None = None
    status: str
    amount: Decimal
    fee: Decimal
    commission: Decimal
    tax: Decimal
    currency: str
    customer_user_id: UUID
    earned_points: int = 0
