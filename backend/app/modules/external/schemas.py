"""Request schemas for the external partner API (Epic 14)."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.identity.schemas import IdentifierIn, UserProfileIn, UserType

# Identifier types a partner-created end-user can be reached on.
_CONTACTABLE = {"email", "phone"}


class ExternalCreateUserRequest(BaseModel):
    """Partner-facing create-user payload.

    Unlike the admin `CreateUserRequest`, there is no `tenant_id` in the body —
    the tenant is derived from the authenticating API key so a partner can only
    ever create users in its own tenant.
    """

    identifiers: list[IdentifierIn] = Field(min_length=1)
    profile: UserProfileIn | None = None
    user_type: UserType = "consumer"
    parent_user_id: UUID | None = None

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> Self:
        """A partner-created user must be contactable by email or phone (D2)."""
        if not any(i.identifier_type in _CONTACTABLE for i in self.identifiers):
            raise ValueError("At least one email or phone identifier is required.")
        return self
