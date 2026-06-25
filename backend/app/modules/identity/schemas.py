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


class WalletTransactionOut(BaseModel):
    """One transaction row surfaced on /me/wallet — same data the mobile
    app shows in its recent-activity feed.

    `direction` is derived from the ledger entry on one of the caller's
    own accounts: CREDIT → "in" (money/points arrived), DEBIT → "out".
    `counterparty_name` is populated for P2P transfers — the other
    user's profile first_name — and null otherwise (top-ups, reward
    issuance, redemptions where the other side is a system/provider
    account with no owning user).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_type: str
    status: str
    amount: str
    fee_amount: str
    currency: str
    created_at: datetime
    direction: Literal["in", "out"]
    counterparty_name: str | None = None


class WalletOut(BaseModel):
    """Authenticated user's own wallet — accounts + recent transactions.

    Used by the mobile-simulator and the eventual real mobile app. Pure
    user-facing: NEVER returns admin-only fields (kyc state, audit ids,
    etc). Tenant is implicit — taken from the session token.
    """

    user_id: UUID
    tenant_id: UUID
    first_name: str | None
    accounts: list[UserAccountOut]
    recent_transactions: list[WalletTransactionOut]


class AdminPinResetResponse(BaseModel):
    """Result of an admin-triggered PIN reset.

    `delivered_via` is `"sms"` in production (notifications module —
    Phase 2). Today it's `"inline"`, meaning the new PIN is included
    in the response so the operator can read it back to the user
    over a verified channel. NEVER expose this endpoint to non-admins.
    """

    user_id: UUID
    delivered_via: Literal["inline", "sms"]
    new_pin: str | None  # populated when delivered_via='inline'


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


# --- Phase mobile A1 — anonymous phone lookup ------------------------------


class AuthStartRequest(BaseModel):
    """Request body for `POST /identity/auth/start`.

    Mirrors the shape of `OtpSendRequest` (tenant_id + phone) so the mobile
    client uses the same input fields across the auth flow. Phone is
    normalised here so the lookup compares canonical forms.
    """

    tenant_id: UUID
    phone: str = Field(min_length=5, max_length=20)

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        """Strip spaces / dashes / parens so visual variants resolve identically."""
        return normalize_phone(v)


class AuthStartResponse(BaseModel):
    """`POST /auth/start` response — drives the mobile auth branch.

    - `needs_otp` → no user exists for (tenant, phone); route through
      OTP → set-PIN registration.
    - `needs_pin` → user already exists; route to PIN entry.
    """

    status: Literal["needs_otp", "needs_pin"]
