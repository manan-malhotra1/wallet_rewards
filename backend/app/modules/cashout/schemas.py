"""Pydantic v2 schemas for the subscriber cash-out module.

A subscriber (consumer) names an AGENT by an identifier and sends money to that
agent — the mirror of agent cash-in. The subscriber + tenant come from the
session token, never the body; only the agent identifier + amount are supplied.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IdentifierType = Literal["phone", "email", "account_number", "card_number"]


class CashOutRequest(BaseModel):
    """Subscriber cash-out payload (auth-gated).

    The identifier resolves the AGENT recipient (tenant-scoped). `pin` is
    optional: include it only when a step-up policy requires re-verification
    for the amount/currency.
    """

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    # Optional derived service to transact under. Omitted -> plain 'cashout'
    # (identical to pre-existing behaviour). Resolved ONCE, up front, and used
    # for every downstream permission / pricing / limits / ledger step (spec §7).
    service_code: str | None = Field(default=None, max_length=50)


class CashOutResponse(BaseModel):
    """Result of a successful cash-out.

    Attributes:
        transaction_id: The double-entry transaction id.
        reference: Customer-facing reference for this cash-out.
        status: Lifecycle state ("COMPLETED" on the happy path).
        amount: The principal credited to the agent.
        fee: Service fee borne by the subscriber (slab pricing).
        commission: Commission paid to the receiving agent from the pool.
        tax: Total tax collected (on fee + commission).
        currency: 3-letter ISO 4217 (uppercase).
        agent_user_id: The agent who received the cash-out.
        earned_points: Points the withdrawing SUBSCRIBER earned from a reward
            rule on this cash-out (0 outside `both` mode, no matching rule, or
            replay).
    """

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    reference: str | None = None
    status: str
    amount: Decimal
    fee: Decimal
    commission: Decimal
    tax: Decimal
    currency: str
    agent_user_id: UUID
    earned_points: int = 0
