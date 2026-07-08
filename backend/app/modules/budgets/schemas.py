"""Pydantic v2 schemas for the budgets module (Phase G.1)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ScopeType = Literal["tenant", "rule"]
WindowType = Literal["rolling_24h", "rolling_7d", "calendar_month", "lifetime"]
BudgetStatus = Literal["active", "paused"]


class BudgetCreateRequest(BaseModel):
    """Admin payload to create a reward budget.

    `scope_id` is required when `scope_type='rule'` (the rule_id); MUST
    be null when `scope_type='tenant'`.
    """

    tenant_id: UUID
    scope_type: ScopeType
    scope_id: UUID | None = None
    currency: str = Field(min_length=3, max_length=3)
    window_type: WindowType
    cap_amount: Decimal = Field(gt=Decimal("0"))
    status: BudgetStatus = "active"


class BudgetOut(BaseModel):
    """Budget resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    scope_type: str
    scope_id: UUID | None
    currency: str
    window_type: str
    cap_amount: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class BudgetConsumptionOut(BaseModel):
    """Budget + computed consumption + percent used. Used by the admin UI."""

    budget: BudgetOut
    consumed_amount: Decimal
    remaining_amount: Decimal
    percent_consumed: float
