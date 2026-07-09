"""Pydantic v2 schemas for the airtime recharge API (Epic 17)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AirtimeRechargeRequest(BaseModel):
    """User-initiated airtime purchase (auth-gated).

    `tenant_id` and `user_id` come from the session token via
    `get_current_user`; the body carries only the target number, network,
    amount, and an optional step-up PIN. Privilege-relevant fields (status,
    merchant, provider reference) are never client-settable.
    """

    msisdn: str = Field(min_length=6, max_length=20)
    network: str = Field(min_length=1, max_length=30)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="ZAR", min_length=3, max_length=10)
    pin: str | None = Field(default=None, min_length=4, max_length=12)


class AirtimeRechargeOut(BaseModel):
    """Airtime recharge resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    msisdn: str
    network: str
    amount: Decimal
    currency: str
    status: str
    transaction_id: UUID
    provider_reference: str | None
    failure_reason: str | None
    completed_at: datetime | None
    created_at: datetime
