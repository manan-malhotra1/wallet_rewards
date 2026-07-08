"""Pydantic v2 schemas for the services catalog module.

`code` is the persistent identifier — once a service has been referenced
in limits / pricing / rules / transactions, renaming it would orphan that
configuration, so the PATCH schema does not include it. Only display_name,
description and status are editable.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ServiceStatus = Literal["active", "disabled"]


class ServiceOut(BaseModel):
    """Service catalog row returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    display_name: str
    description: str | None
    status: ServiceStatus
    created_at: datetime
    updated_at: datetime


class ServiceCreateRequest(BaseModel):
    """Create payload — code locked at creation."""

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


class ServiceUpdateRequest(BaseModel):
    """Patch body for catalog admin edits."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: ServiceStatus | None = None
