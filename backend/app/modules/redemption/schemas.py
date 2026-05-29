"""Pydantic v2 schemas for the redemption module."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProviderRegistrationRequest(BaseModel):
    """Test-only request to register a redemption provider.

    Creates the provider row AND the associated provider_redemption_wallet
    account (in PTS) atomically.
    """

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    status_check_url: str | None = Field(default=None, max_length=500)
    max_retries: int = Field(default=3, ge=0, le=20)
    retry_interval_secs: int = Field(default=300, ge=1)
    escalate_after_mins: int = Field(default=60, ge=1)


class ProviderOut(BaseModel):
    """Provider resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    redemption_wallet_account_id: UUID
    status_check_url: str | None
    max_retries: int
    retry_interval_secs: int
    escalate_after_mins: int
    status: str


class InitiateRedemptionRequest(BaseModel):
    """Test-only redemption initiation payload.

    `user_id` is in the body because Phase D has no auth (carried over from
    Phase B). Phase F resolves it from the authenticated session.
    """

    tenant_id: UUID
    user_id: UUID
    provider_id: UUID
    points_amount: Decimal = Field(gt=Decimal("0"))


class ConfirmRedemptionRequest(BaseModel):
    """Test endpoint payload simulating provider success callback (Pay-PRD-0690)."""

    tenant_id: UUID
    external_reference: str | None = Field(default=None, max_length=255)


class FailRedemptionRequest(BaseModel):
    """Test endpoint payload simulating provider failure (Pay-PRD-0700)."""

    tenant_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class RedemptionOut(BaseModel):
    """Redemption resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    provider_id: UUID
    transaction_id: UUID
    points_amount: Decimal
    status: str
    external_reference: str | None
    failure_reason: str | None
    completed_at: datetime | None
    created_at: datetime
