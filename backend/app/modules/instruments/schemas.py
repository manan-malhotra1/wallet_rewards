"""Pydantic v2 schemas for the instruments catalog module.

`code` (up to 10 chars) is immutable after creation — every currency
column across the platform stores this value verbatim. `account_type`
fixes the kind of account auto-provisioned for users holding the
instrument: 'financial_wallet' for fiat, 'points_account' for loyalty
points. New types can be added if the platform grows new account kinds.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

InstrumentStatus = Literal["active", "disabled"]

# Account-type values the create endpoint will accept. Matches the
# ACCOUNT_TYPES constant on the Account model; only the two user-side
# kinds are exposed here (system account types are platform-managed).
InstrumentAccountType = Literal["financial_wallet", "points_account"]


class InstrumentOut(BaseModel):
    """Instrument catalog row returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    symbol: str
    display_name: str
    description: str | None
    account_type: str
    status: InstrumentStatus
    created_at: datetime
    updated_at: datetime


class InstrumentCreateRequest(BaseModel):
    """Create payload.

    `assign_to_existing_users` controls a one-shot backfill — when true
    the service creates one account per existing user in the tenant
    (idempotent) so the new instrument is immediately spendable.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    code: str = Field(
        min_length=2,
        max_length=10,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description=(
            "Uppercase identifier stored in every currency column on the "
            "platform. Cannot be changed after creation."
        ),
    )
    symbol: str = Field(min_length=1, max_length=10)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    account_type: InstrumentAccountType
    assign_to_existing_users: bool = Field(
        default=False,
        description=(
            "When true, immediately create one account per existing user "
            "for this instrument so they can transact right away."
        ),
    )


class InstrumentUpdateRequest(BaseModel):
    """Patch body — display_name / description / status / symbol."""

    model_config = ConfigDict(extra="forbid")

    symbol: str | None = Field(default=None, min_length=1, max_length=10)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: InstrumentStatus | None = None
