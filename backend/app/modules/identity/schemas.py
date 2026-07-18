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
UserType = Literal["consumer", "agent", "super_agent", "merchant", "head_merchant"]


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
    # User type (Epic 12). Defaults to consumer so existing callers are
    # unaffected. `parent_user_id` is only valid for agent/merchant types —
    # compatibility is enforced in the service layer.
    user_type: UserType = "consumer"
    parent_user_id: UUID | None = None
    # Optional referrer's code (Epic 10 / WAL-77). When supplied and valid, a
    # `referrals` row is created and any active signup-trigger referral rule
    # fires. Absent / null → organic signup, no referral.
    referral_code: str | None = Field(default=None, min_length=1, max_length=16)


class ChangeUserTypeRequest(BaseModel):
    """Body for PATCH /identity/users/{user_id}/type (Epic 12).

    `reason` is mandatory — it is recorded on the audit_log entry so type
    changes are traceable (NFR-0250). `parent_user_id` follows the same
    Decision D4 compatibility rules as creation.
    """

    new_type: UserType
    parent_user_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=500)


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
    user_type: str
    parent_user_id: UUID | None = None
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
    user_type: str
    parent_user_id: UUID | None
    # Resolved display name of the parent user (agent/merchant hierarchy) so the
    # UI never shows a bare parent id. None when there is no parent or it has no
    # resolvable name — the UI then falls back to a short id.
    parent_name: str | None = None
    created_at: datetime
    identifiers: list[IdentifierOut]
    profile: UserProfileOut | None
    accounts: list[UserAccountOut]
    # PIN-lockout state (Redis-backed, NFR-0190) — lets the UI show a "Locked"
    # pill + countdown and offer an Unlock action. `unlocks_in_seconds` is the
    # remaining lockout TTL, null when the user isn't locked.
    is_locked: bool = False
    unlocks_in_seconds: int | None = None


class AdminUnlockResponse(BaseModel):
    """Result of an admin unlock — releases a PIN lockout without a PIN change."""

    user_id: UUID
    # The lock state BEFORE the clear, so the UI can tell the operator whether
    # the user was actually locked (vs. an idempotent no-op unlock).
    was_locked: bool


class WalletTransactionOut(BaseModel):
    """One transaction row surfaced on /me/wallet — same data the mobile
    app shows in its recent-activity feed.

    `direction` is derived from the ledger entry on one of the caller's
    own accounts: CREDIT → "in" (money/points arrived), DEBIT → "out".
    `counterparty_name` is populated for P2P transfers — the other
    user's profile first_name — and null otherwise (funds, reward
    issuance, redemptions where the other side is a system/provider
    account with no owning user).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # Customer-facing reference `S_<YYYYMMDDHHMMSS><NNNNNN>`. Null only for the
    # legacy window before a row was backfilled; always set on new transactions.
    reference: str | None = None
    transaction_type: str
    status: str
    amount: str
    fee_amount: str
    # Display-only charge siblings (Epic 20): the commission paid to an agent and
    # the tax collected on this transaction. Zero for transactions that bear none.
    commission_amount: str
    tax_amount: str
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
