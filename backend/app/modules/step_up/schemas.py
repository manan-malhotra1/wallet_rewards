"""Pydantic v2 schemas for the step-up module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Only the user-initiated transaction types make sense as step-up
# scopes. Fund is a system-initiated flow (already auth'd via the
# external source) so it's deliberately excluded.
TransactionType = Literal["p2p", "redemption"]


class StepUpPolicyCreateRequest(BaseModel):
    """Admin create payload for a new step-up policy."""

    tenant_id: UUID
    transaction_type: TransactionType
    currency: str = Field(min_length=3, max_length=3)
    threshold_amount: Decimal = Field(ge=Decimal("0"))


class StepUpPolicyOut(BaseModel):
    """Step-up policy resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    transaction_type: str
    currency: str
    threshold_amount: Decimal
    created_at: datetime
    updated_at: datetime
