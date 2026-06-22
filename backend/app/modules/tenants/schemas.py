"""Pydantic v2 schemas for the tenants module.

Phase 1 surfaces the tenant *identity card*: name (editable),
business_type (editable Wallet/Rewards/Both), plus the read-only
keycloak_realm tag the admin UI displays next to the ID.
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Single source of truth for the business_type enum on the wire side.
# Backend CHECK constraint (ck_tenants_business_type) is the database mirror.
BusinessType = Literal["wallet", "rewards", "both"]


class TenantOut(BaseModel):
    """Tenant resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    business_type: BusinessType
    keycloak_realm: str | None
    base_currency: str | None
    status: str
    created_at: datetime


class TenantUpdateRequest(BaseModel):
    """Patch body for tenant identity-card edits.

    Both fields are optional — the UI may send just `name` or just
    `business_type` depending on which control the operator touched. An
    empty body is rejected by the service layer (no-op call indicates a
    client bug, not a valid request).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New display name. Must remain unique across all tenants.",
    )
    business_type: BusinessType | None = Field(
        default=None,
        description="Which services are switched on for this tenant.",
    )
