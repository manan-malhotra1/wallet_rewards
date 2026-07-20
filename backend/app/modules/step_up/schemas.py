"""Pydantic v2 schemas for the step-up module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# The user-initiated transaction types that `enforce_step_up` guards — every
# money path that takes a user PIN. Fund/withdraw are system/admin-initiated
# (already auth'd) and are deliberately excluded. Must stay in sync with the
# enforce_step_up call sites (payments/redemption/cashout/cashin/airtime); if a
# new user-initiated money path is added, add its transaction_type here so an
# admin can configure a step-up policy for it via config maker-checker.
TransactionType = Literal["p2p", "redemption", "cashout", "cash_in", "airtime_recharge"]


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
