"""Request schemas for the external partner API (Epic 14).

Deliberately a RESTRICTED shape (Epic 14 S7 / mass-assignment hardening,
finding H1): a partner CANNOT set `user_type`, `parent_user_id`, or an
identifier's `verified` flag — those are privilege/trust-relevant and are
forced server-side in the router. Reusing the admin `CreateUserRequest` /
`IdentifierIn` shapes for an untrusted caller would let a partner pick its own
limit/pricing tier or assert unverified contact details as verified.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.modules.identity.schemas import IdentifierType, UserProfileIn

# Identifier types a partner-created end-user can be reached on.
_CONTACTABLE = {"email", "phone"}


class ExternalIdentifierIn(BaseModel):
    """A partner-supplied identifier — no `verified` flag.

    Partners cannot assert that a phone/email is verified; the platform only
    marks an identifier verified through its own OTP flow.
    """

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)


class ExternalCreateUserRequest(BaseModel):
    """Partner-facing create-user payload.

    No `tenant_id` (derived from the API key), and no `user_type` /
    `parent_user_id` — the endpoint forces `consumer` with no parent so a
    partner can't self-assign a limit/pricing tier or graft the tenant
    hierarchy (S7 H1).
    """

    identifiers: list[ExternalIdentifierIn] = Field(min_length=1, max_length=10)
    profile: UserProfileIn | None = None

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> Self:
        """A partner-created user must be contactable by email or phone (D2)."""
        if not any(i.identifier_type in _CONTACTABLE for i in self.identifiers):
            raise ValueError("At least one email or phone identifier is required.")
        return self
