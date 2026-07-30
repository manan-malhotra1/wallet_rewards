"""Pydantic v2 schemas for the tenants module.

Phase 1 surfaces the tenant *identity card*: name (editable),
business_type (editable Wallet/Rewards/Both), plus the read-only
keycloak_realm tag the admin UI displays next to the ID. It also carries
the per-tenant branding (accent/light colours + logo URL) so the admin UI
can theme itself when it loads a tenant.
"""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Single source of truth for the business_type enum on the wire side.
# Backend CHECK constraint (ck_tenants_business_type) is the database mirror.
BusinessType = Literal["wallet", "rewards", "both"]

# Accepts "#RRGGBB" or "#RRGGBBAA" (case-insensitive). The DB column is
# String(9) so the 8-digit-with-alpha form is the longest value that fits.
HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# A branding icon must be a browser-loadable http(s) URL — no data: URIs,
# no relative paths (the admin UI renders it straight into an <img src>).
HTTP_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


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
    # Per-tenant branding — nullable; absence means "fall back to app default".
    brand_accent_color: str | None = None
    brand_light_color: str | None = None
    brand_icon_url: str | None = None


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


class TenantBrandingOut(BaseModel):
    """The three branding fields the admin UI themes itself from.

    All nullable — a null value means the tenant has no override for that
    field and the UI should fall back to the app default.
    """

    model_config = ConfigDict(from_attributes=True)

    brand_accent_color: str | None = None
    brand_light_color: str | None = None
    brand_icon_url: str | None = None


class TenantBrandingUpdate(BaseModel):
    """Direct-edit body for a tenant's cosmetic branding.

    Every field is optional and nullable: a provided value sets it, an
    explicit `null` clears it back to the app default. Colours must be
    "#RRGGBB" or "#RRGGBBAA" hex; the icon must be an http(s) URL. Validation
    runs only when a value is provided (null passes through to clear).
    """

    model_config = ConfigDict(extra="forbid")

    brand_accent_color: Annotated[str | None, Field(default=None, max_length=9)] = None
    brand_light_color: Annotated[str | None, Field(default=None, max_length=9)] = None
    brand_icon_url: Annotated[str | None, Field(default=None, max_length=2048)] = None

    @field_validator("brand_accent_color", "brand_light_color")
    @classmethod
    def _validate_hex_color(cls, value: str | None) -> str | None:
        """Reject any non-null colour that isn't 6- or 8-digit hex."""
        if value is not None and not HEX_COLOR_PATTERN.match(value):
            raise ValueError("must be a hex colour like '#243B8F' or '#243B8FCC'")
        return value

    @field_validator("brand_icon_url")
    @classmethod
    def _validate_icon_url(cls, value: str | None) -> str | None:
        """Reject any non-null icon URL that isn't http(s)."""
        if value is not None and not HTTP_URL_PATTERN.match(value):
            raise ValueError("must be an http(s) URL")
        return value
