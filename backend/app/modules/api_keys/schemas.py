"""Schemas for admin API-key management (Epic 14 S2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    """Admin payload to mint a new API key for a tenant."""

    tenant_id: UUID
    label: str | None = Field(default=None, max_length=100)


class ApiKeyOut(BaseModel):
    """API-key resource as listed — never includes the secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    key_id: str
    label: str | None
    status: str
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    """Returned ONCE at creation — carries the plaintext secret. It is never
    retrievable again; the operator must copy it now."""

    secret: str
