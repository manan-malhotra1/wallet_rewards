"""Pydantic v2 schemas for the roles module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateRoleRequest(BaseModel):
    """Admin payload for creating a role."""

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class UpdateRoleRequest(BaseModel):
    """PATCH body — partial update."""

    description: str | None = Field(default=None, max_length=500)
    status: Literal["active", "inactive"] | None = None


class SetPermissionRequest(BaseModel):
    """Create/update a single (role, transaction_type) permission."""

    transaction_type: str = Field(min_length=1, max_length=50)
    permitted: bool = True


class AssignRoleRequest(BaseModel):
    """Assign a role to a user."""

    role_id: UUID


class RoleOut(BaseModel):
    """Role resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    status: str
    created_at: datetime


class RolePermissionOut(BaseModel):
    """One permission row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role_id: UUID
    transaction_type: str
    permitted: bool


class UserRoleOut(BaseModel):
    """One user-role assignment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    role_id: UUID
    assigned_at: datetime
