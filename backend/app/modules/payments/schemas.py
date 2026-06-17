"""Pydantic v2 schemas for the payments module."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# UUID is still used by P2PResponse (sender_user_id / recipient_user_id).

IdentifierType = Literal["phone", "email", "account_number", "card_number"]


class RecipientIdentifier(BaseModel):
    """The way the sender refers to the recipient (Pay-PRD-0250)."""

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)


class P2PRequest(BaseModel):
    """P2P transfer payload (Phase F.4 — auth-gated).

    `tenant_id` and `sender_user_id` are no longer accepted in the body —
    both come from the session token via `get_current_user`. Spoofing the
    sender is no longer possible.

    `pin` is optional: include it only when a `step_up_policies` row
    requires re-verification for the requested amount/currency. The
    backend rejects with `step_up_required` if missing when needed; the
    mobile client retries with the PIN attached.
    """

    recipient: RecipientIdentifier
    # Decimal preserves precision; FastAPI accepts JSON strings or numbers.
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=255)
    pin: str | None = Field(default=None, min_length=4, max_length=12)


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
