"""Pydantic v2 schemas for the tenants module."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantOut(BaseModel):
    """Tenant resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    deployment_mode: str
    base_currency: str | None
    status: str
    created_at: datetime
