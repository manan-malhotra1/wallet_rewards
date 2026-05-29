"""Pydantic v2 request/response schemas for the identity module.

All identifier values are accepted as strings; validation of format (phone
shape, email regex) is intentionally lenient in Phase A. Strict format
validation is added in Phase 2 alongside the OTP flow.
"""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

IdentifierType = Literal["phone", "email", "account_number", "card_number"]


class IdentifierIn(BaseModel):
    """One identifier provided at registration time."""

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    verified: bool = False


class UserProfileIn(BaseModel):
    """Optional profile data provided at registration."""

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None


class CreateUserRequest(BaseModel):
    """Test-only registration payload.

    `tenant_id` is accepted in the body because Phase A has no auth.
    Production registration (Phase 2) will resolve tenant from the request's
    Keycloak realm context.
    """

    tenant_id: UUID
    identifiers: list[IdentifierIn] = Field(min_length=1)
    profile: UserProfileIn | None = None


class IdentifierOut(BaseModel):
    """An identifier echoed back on responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    identifier_type: str
    identifier_value: str
    verified: bool


class UserOut(BaseModel):
    """User resource returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    status: str
    identifiers: list[IdentifierOut]


class ResolveResponse(BaseModel):
    """Result of identifier resolution (Pay-PRD-0060)."""

    user_id: UUID
    tenant_id: UUID
    identifier_type: str
