"""Pydantic v2 schemas for the payments module.

Hosts request/response models for the P2P transfer endpoint and the
mobile-facing demo fund endpoint (Pay-PRD-0320). All `tenant_id` /
`user_id` resolution comes from the session token — never the request
body.
"""

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
    """Result of a successful P2P transfer.

    Attributes:
        transaction_id: The double-entry transaction id (Pay-PRD-0170).
        status: Lifecycle state of the transaction ("COMPLETED" on the
            happy path).
        amount: The transferred amount the recipient receives (echoes the
            request).
        fee: Service charge debited from the sender on top of `amount`
            (Pay-PRD-0260). Zero when no pricing config applies.
        total_debited: What actually left the sender's wallet
            (`amount + fee`) — saves the client doing the arithmetic.
        currency: 3-letter ISO 4217 (uppercase) — echoes the request.
        sender_user_id: The authenticated sender (resolved from the
            session token, NOT the request body).
        recipient_user_id: Resolved from the recipient identifier.
        created_at: When the transaction landed (UTC).
        earned_points: Total PTS issued to the sender by the rules engine for
            this transfer — `0` when the tenant is not in `both` mode or no rule
            fired. Surfacing this avoids a polling round-trip on the mobile
            success screen.
    """

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    # Customer-facing reference `S_<YYYYMMDDHHMMSS><NNNNNN>` for this transfer.
    reference: str | None = None
    status: str
    amount: Decimal
    fee: Decimal
    total_debited: Decimal
    currency: str
    sender_user_id: UUID
    recipient_user_id: UUID
    created_at: datetime
    earned_points: int = 0
