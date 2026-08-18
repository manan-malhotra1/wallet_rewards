"""Pydantic v2 schemas for the airtime recharge API (Epic 17)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AirtimeRechargeRequest(BaseModel):
    """User-initiated airtime purchase (auth-gated).

    `tenant_id` and `user_id` come from the session token via
    `get_current_user`; the body carries only the target number, network,
    amount, and an optional step-up PIN. Privilege-relevant fields (status,
    merchant, provider reference) are never client-settable — and `extra=forbid`
    rejects any unexpected field outright rather than silently dropping it (S7 A7).
    """

    model_config = ConfigDict(extra="forbid")

    msisdn: str = Field(min_length=6, max_length=20)
    network: str = Field(min_length=1, max_length=30)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="ZAR", min_length=3, max_length=10)
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    # Optional derived service to transact under. Omitted -> plain
    # 'airtime_recharge' (identical to pre-existing behaviour). Resolved ONCE,
    # up front, and used for every downstream permission / pricing / limits /
    # ledger step (spec §7).
    service_code: str | None = Field(default=None, max_length=50)


class AirtimeRechargeOut(BaseModel):
    """Airtime recharge resource returned by the API.

    `earned_points` is the reward the buyer earned when the recharge vended
    successfully in-request (both-mode tenants). It is 0 on a PENDING / REVERSED
    outcome and on reads — rewards fire only on the successful-vend completion.
    """

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
    earned_points: int = 0


class AirtimeCallbackRequest(BaseModel):
    """HMAC-verified provider callback payload (Epic 17 S5).

    The provider POSTs this with an `X-Sasai-Signature` header; the signature is
    verified against the merchant's decrypted callback secret BEFORE this schema
    is parsed, so a malformed body can't leak existence ahead of the HMAC check.
    """

    outcome: Literal["completed", "failed"]
    provider_reference: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=500)


class AirtimeResolveRequest(BaseModel):
    """Operator override to resolve a stuck PENDING recharge (Epic 17 S5).

    `tenant_id` is in the body because platform-admins span tenants (matches the
    reconciliation pattern). Used when the provider never called back.
    """

    tenant_id: UUID
    outcome: Literal["COMPLETED", "REVERSED"]
    provider_reference: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=500)
