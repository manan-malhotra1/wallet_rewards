"""Pydantic v2 request/response schemas for the identity module.

All identifier values are accepted as strings; validation of format (phone
shape, email regex) is intentionally lenient in Phase A. Strict format
validation is added in Phase 2 alongside the OTP flow.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.utils.normalize import normalize_phone

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


class UserAccountOut(BaseModel):
    """Account summary surfaced on the user-detail response.

    Includes the derived balance + reserved so the admin UI can render a
    full account row without an extra round trip per account.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_type: str
    currency: str
    status: str
    balance: str
    reserved_balance: str
    available_balance: str


class UserProfileOut(BaseModel):
    """User profile fields (KYC). All optional."""

    model_config = ConfigDict(from_attributes=True)

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None


class UserDetailOut(BaseModel):
    """Full user-detail response — admin-only.

    Surfaces the data the admin UI needs to render the user drawer:
    identifiers, profile, accounts with balances. Transactions /
    redemptions arrive via the audit log + reconciliation surfaces.
    """

    id: UUID
    tenant_id: UUID
    status: str
    created_at: datetime
    identifiers: list[IdentifierOut]
    profile: UserProfileOut | None
    accounts: list[UserAccountOut]


# --- Phase F.2 — PIN/OTP/session flow --------------------------------------


class OtpSendRequest(BaseModel):
    """Request body for `POST /identity/otp/send`."""

    tenant_id: UUID
    phone: str = Field(min_length=5, max_length=20)

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        """Strip spaces / dashes / parens so the canonical form is what
        reaches the OTP lookup + the unique identifier index."""
        return normalize_phone(v)


class OtpSendResponse(BaseModel):
    """`POST /otp/send` response.

    `otp` is populated ONLY when the server is configured with
    `OTP_DEV_RETURN=true` (local dev only) — see Settings. In production the
    field is omitted and SMS gateway delivers the code.
    """

    delivered: bool
    otp: str | None = None  # local-dev only


class OtpVerifyRequest(BaseModel):
    """Request body for `POST /identity/otp/verify`."""

    tenant_id: UUID
    phone: str = Field(min_length=5, max_length=20)
    otp: str = Field(min_length=4, max_length=10)

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        return normalize_phone(v)


class OtpVerifyResponse(BaseModel):
    """`POST /otp/verify` returns the short-lived registration token."""

    registration_token: str
    expires_in: int


class PinSetRequest(BaseModel):
    """Request body for `POST /identity/pin/set`."""

    registration_token: str = Field(min_length=8)
    pin: str = Field(min_length=4, max_length=6)


class PinAuthRequest(BaseModel):
    """Request body for `POST /identity/auth/pin`."""

    tenant_id: UUID
    phone: str = Field(min_length=5, max_length=20)
    pin: str = Field(min_length=4, max_length=6)

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        return normalize_phone(v)


class SessionTokenResponse(BaseModel):
    """`POST /auth/pin` returns the opaque bearer token."""

    session_token: str
    expires_in: int


class LogoutResponse(BaseModel):
    """`POST /auth/logout` ack."""

    ok: bool = True
