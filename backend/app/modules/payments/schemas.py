"""Pydantic v2 schemas for the payments module."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IdentifierType = Literal["phone", "email", "account_number", "card_number"]


class RecipientIdentifier(BaseModel):
    """The way the sender refers to the recipient (Pay-PRD-0250)."""

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)


class P2PRequest(BaseModel):
    """Test-only P2P transfer payload.

    `sender_user_id` is in the body for Phase B (no auth). Phase 2 resolves
    it from the authenticated session and removes this field from the schema.
    """

    tenant_id: UUID
    sender_user_id: UUID
    recipient: RecipientIdentifier
    # Decimal preserves precision; FastAPI accepts JSON strings or numbers.
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=255)


class P2PResponse(BaseModel):
    """Result of a successful P2P transfer."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    status: str
    amount: Decimal
    currency: str
    sender_user_id: UUID
    recipient_user_id: UUID
    created_at: datetime
