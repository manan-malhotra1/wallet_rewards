"""Pydantic v2 schemas for the segments module."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SegmentCreateRequest(BaseModel):
    """Admin create payload."""

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class SegmentOut(BaseModel):
    """Segment resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class AddUserToSegmentRequest(BaseModel):
    """Admin payload to assign a user to a segment."""

    user_id: UUID
