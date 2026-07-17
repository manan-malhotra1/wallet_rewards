"""Pydantic v2 schemas for the change-PIN module.

A user changes their own PIN — a charged self-service operation. PINs are
write-only: `current_pin` / `new_pin` are accepted on the request and NEVER
echoed back on any response (NFR-0170). The response carries only the charge
breakdown and the optional fee-transaction id.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChangePinRequest(BaseModel):
    """Change-PIN payload (auth-gated; the acting user comes from the session).

    Both PINs are 4-12 chars; the numeric-format check happens in the service
    (`_validate_pin_format`) so the error surfaces as the standard
    `invalid_pin_format` 422. `current_pin` gates the change exactly like login
    (verified against the stored hash, with lockout on repeated misses).
    """

    current_pin: str = Field(min_length=4, max_length=12)
    new_pin: str = Field(min_length=4, max_length=12)
    currency: str = Field(default="ZAR", min_length=3, max_length=3)


class ChangePinResponse(BaseModel):
    """Result of a successful PIN change — charge breakdown only, never a PIN.

    Attributes:
        status: Lifecycle state ("completed").
        fee: Service fee charged for the change (may be an explicit zero).
        tax: Total tax charged on the fee.
        currency: 3-letter ISO 4217 (uppercase).
        transaction_id: The fee transaction id, or None when the fee was zero
            (a zero-fee change moves no money, so no ledger transaction exists).
    """

    model_config = ConfigDict(from_attributes=True)

    status: str
    fee: Decimal
    tax: Decimal
    currency: str
    transaction_id: UUID | None = None
