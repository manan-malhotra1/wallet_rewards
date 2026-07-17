"""Schemas for admin API-key management (Epic 14 S2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    """Admin payload to mint a new API key for a tenant."""

    tenant_id: UUID
    label: str | None = Field(default=None, max_length=100)
    merchant_user_id: UUID | None = Field(
        default=None,
        description=(
            "When set, the key can call merchant-cashin, funding consumers from "
            "THIS merchant's wallet; must reference a merchant-type user in the "
            "same tenant."
        ),
    )


class ApiKeyOut(BaseModel):
    """API-key resource as listed — never includes the secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    key_id: str
    label: str | None
    status: str
    # Set only on merchant-bound keys — surfaces which keys carry the
    # merchant-cashin capability. Never a secret.
    merchant_user_id: UUID | None
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    """Returned ONCE at creation — carries the plaintext secret. It is never
    retrievable again; the operator must copy it now."""

    secret: str
