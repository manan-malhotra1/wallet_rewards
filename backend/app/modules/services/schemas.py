"""Pydantic v2 schemas for the services catalog module.

`code` is the persistent identifier — once a service has been referenced
in limits / pricing / rules / transactions, renaming it would orphan that
configuration, so the PATCH schema does not include it. display_name,
description, status and the two access-policy allow-lists are editable.

Access-policy representation (matches the `Service` model + the mobile
`/me/services` query): both `allowed_user_types` and `allowed_channels` are
nullable lists where **NULL/omitted means "unrestricted"** (all values allowed)
and a **non-empty list is an allow-list**. An **empty list `[]` is a distinct,
meaningful value** — "restrict to none on this dimension" (for user_types that
is operator-only). Because NULL and `[]` differ in meaning, `ServiceOut` keeps
NULL as `null` and never normalises it to `[]`; on update, a `None` field means
"leave unchanged" while `[]` explicitly sets the empty allow-list.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.shared.models import USER_TYPES

ServiceStatus = Literal["active", "disabled"]

# Canonical channel set for the `allowed_channels` allow-list. Single source of
# truth for the values documented on the `Service.allowed_channels` column.
SERVICE_CHANNELS: tuple[str, ...] = ("web", "api", "mobile", "ussd", "admin", "system")


def _validate_user_types(value: list[str] | None) -> list[str] | None:
    """Reject any user_type not in the canonical set (empty/None pass through).

    Raises:
        ValueError: at least one element is not a known user type (→ 422).
    """
    if value is None:
        return value
    unknown = [v for v in value if v not in USER_TYPES]
    if unknown:
        raise ValueError(f"unknown user_type(s) {unknown}; allowed: {list(USER_TYPES)}")
    return value


def _validate_channels(value: list[str] | None) -> list[str] | None:
    """Reject any channel not in the canonical set (empty/None pass through).

    Raises:
        ValueError: at least one element is not a known channel (→ 422).
    """
    if value is None:
        return value
    unknown = [v for v in value if v not in SERVICE_CHANNELS]
    if unknown:
        raise ValueError(f"unknown channel(s) {unknown}; allowed: {list(SERVICE_CHANNELS)}")
    return value


# Reusable validated field types — keep create + update DRY and consistent.
AllowedUserTypes = Annotated[list[str] | None, AfterValidator(_validate_user_types)]
AllowedChannels = Annotated[list[str] | None, AfterValidator(_validate_channels)]


class ServiceOut(BaseModel):
    """Service catalog row returned by the API.

    `allowed_user_types` / `allowed_channels` are returned verbatim from the
    row: `null` = unrestricted, `[]` = restrict-to-none, a list = allow-list.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    display_name: str
    description: str | None
    status: ServiceStatus
    kind: str
    base_service_code: str | None
    allowed_user_types: list[str] | None
    allowed_channels: list[str] | None
    created_at: datetime
    updated_at: datetime


class ServiceCreateRequest(BaseModel):
    """Create payload — code locked at creation.

    Only derived services can be created through this endpoint (spec §6):
    base services ship with the platform and are provisioned per tenant by
    `provision_tenant_defaults`, not created here. `kind` is therefore not a
    client-supplied field at all — the service layer always sets it to
    'derived' — and `base_service_code` is required.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]*$",
        description=(
            "Lowercase identifier used in transaction_type fields across the "
            "platform. Cannot be changed after creation."
        ),
    )
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Required: base services ship with the platform and are provisioned per
    # tenant, so the only thing this endpoint creates is a derived service
    # (spec §6). `kind` is deliberately NOT a client field.
    base_service_code: str = Field(
        min_length=2,
        max_length=50,
        description="Code of the platform base service this derives from.",
    )
    # NULL/omitted = unrestricted on that dimension; [] = restrict-to-none.
    allowed_user_types: AllowedUserTypes = None
    allowed_channels: AllowedChannels = None


class ServiceUpdateRequest(BaseModel):
    """Patch body for catalog admin edits.

    A field left as `None` (omitted) leaves that column unchanged so a partial
    edit never wipes an existing policy; send `[]` to explicitly clear a
    dimension to restrict-to-none.

    `base_service_code` is deliberately absent: re-pointing a live derived
    service at a different execution path would silently repurpose its
    pricing and limits, so it is immutable. Unlike `code` (which is simply
    documented as immutable above), this schema's `extra="forbid"` turns any
    attempt to set it into a 422 rather than the spec's proposed 409 — a
    stricter, simpler contract than spec §6 describes (deviation noted for
    the controller).
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: ServiceStatus | None = None
    allowed_user_types: AllowedUserTypes = None
    allowed_channels: AllowedChannels = None
