"""Pydantic v2 request/response schemas for the identity module.

All identifier values are accepted as strings; validation of format (phone
shape, email regex) is intentionally lenient in Phase A. Strict format
validation is added in Phase 2 alongside the OTP flow.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.utils.normalize import normalize_phone

IdentifierType = Literal["phone", "email", "account_number", "card_number"]
# User types are configurable at runtime (user-types catalog, 2026-08-23), so
# this cannot be a Literal. Validity is enforced in the service against the
# tenant's own resolved list — see `user_types.service.assert_user_type_valid`.
UserType = str


class IdentifierIn(BaseModel):
    """One identifier provided at registration time."""

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    verified: bool = False


class AddIdentifierRequest(BaseModel):
    """Body for `POST /identity/users/{user_id}/identifiers` (Epic 27, Story 27.1).

    Adds a post-registration identifier to an EXISTING user. `card_number` is
    deliberately EXCLUDED from the accepted types: a raw PAN must never be
    stored (PCI scope — only a tokenised reference in Phase 2). A `card_number`
    body therefore 422s at validation, which is the intended rejection.
    """

    identifier_type: Literal["phone", "email", "account_number"]
    identifier_value: str = Field(min_length=1, max_length=255)


class ParentIdentifierIn(BaseModel):
    """A supervisor named by one of their registered identifiers.

    Operators and partners hold phone numbers, not UUIDs, so this is the
    practical way to attach a supervisor at onboarding (spec §7.2). Mutually
    exclusive with `parent_user_id`; resolution is tenant-scoped.
    """

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)


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
    # The identifier form of the same supervisor reference (spec §7.2).
    # Mutually exclusive with `parent_user_id`; BOTH omitted is the normal case
    # and stays frictionless — a supervisor is never required.
    parent_identifier: ParentIdentifierIn | None = None
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
    # False for a commission wallet: real money the user holds but cannot
    # transact against until a disbursement run moves it (spec §5, §10).
    spendable: bool = True


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
    # Admin access-lock level derived from status (migration 0045): active →
    # active, suspended → login_locked, txn_locked → transactions_locked,
    # closed → closed. Lets the UI render the current lock state.
    access_level: str
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
    # Per-currency spendable balance — main wallets only, EXCLUDING accrued
    # commission (spec §10). Values are decimal strings, matching the account
    # balance fields. Keyed by currency code.
    spendable_total: dict[str, str] = {}
    # PIN-lockout state (Redis-backed, NFR-0190) — lets the UI show a "Locked"
    # pill + countdown and offer an Unlock action. `unlocks_in_seconds` is the
    # remaining lockout TTL, null when the user isn't locked.
    is_locked: bool = False
    unlocks_in_seconds: int | None = None


AccessLevel = Literal["active", "login_locked", "transactions_locked"]


class AccessLevelRequest(BaseModel):
    """Body for `POST /identity/users/{user_id}/access` (admin access-lock).

    `level` is the operator-facing access level; the service maps it to
    `user.status`. `transactions_locked` still permits login/read but blocks
    every user-initiated money path; `login_locked` also kills live sessions.
    `closed` is terminal and is NOT settable here.
    """

    level: AccessLevel


class AccessLevelResponse(BaseModel):
    """Result of an access-level change — the applied level + resulting status."""

    user_id: UUID
    status: str
    level: AccessLevel


class AdminUnlockResponse(BaseModel):
    """Result of an admin unlock — releases a PIN lockout without a PIN change."""

    user_id: UUID
    # The lock state BEFORE the clear, so the UI can tell the operator whether
    # the user was actually locked (vs. an idempotent no-op unlock).
    was_locked: bool


class MyServiceOut(BaseModel):
    """One service tile the signed-in mobile user may initiate.

    Powers the app's home screen: the caller gets only the services their
    user_type + the `mobile` channel are allowed to initiate (see
    `list_my_services`). `description` is optional copy for the tile subtitle.
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    display_name: str
    description: str | None = None
    # NULL for a base service; for a derived one, the base it delegates to —
    # so the app can pick an icon/behaviour by base without knowing every
    # derived code (spec §12.1).
    base_service_code: str | None = None


class WindowUsageOut(BaseModel):
    """Consumed-vs-cap figures for one rolling window (daily/weekly/monthly).

    `consumed_*` is what the user has already moved in the window; `cap_*` is the
    configured ceiling — `None` means "no limit" on that axis (either the cap
    column is NULL or the wallet has no limit config at all). Money is a decimal
    string; counts are ints.
    """

    consumed_count: int
    cap_count: int | None = None
    consumed_value: str
    cap_value: str | None = None


class DirectionUsageOut(BaseModel):
    """A single direction's (send or receive) consumption across all windows."""

    daily: WindowUsageOut
    weekly: WindowUsageOut
    monthly: WindowUsageOut


class MyLimitsOut(BaseModel):
    """One currency wallet's send/receive limit consumption — `GET /me/limits`.

    Surfaces, per financial-wallet currency, how much of the rolling
    daily/weekly/monthly SEND and RECEIVE caps the signed-in user has consumed
    versus the configured caps. A wallet with no limit config still appears, with
    every cap `None` and the consumed figures informational.
    """

    currency: str
    send: DirectionUsageOut
    receive: DirectionUsageOut


class RewardProgressOut(BaseModel):
    """Progress bar for one catalog rule — `current` of `target`, plus a caption.

    For a milestone rule `current`/`target` count matching transactions; for a
    streak, streak units; for the binary rule types (first_time / value_based /
    campaign / composite / referral) it is 0-or-1 of 1. `label` names the
    activity the rule tracks (e.g. "P2P transfers").
    """

    current: int
    target: int
    label: str


class RewardCatalogItemOut(BaseModel):
    """One reward rule as shown to a mobile user — `GET /me/rewards` catalog entry.

    `status` is "locked" (no progress yet), "in_progress" (partway), or "earned"
    (the rule has completed for this user). `currency` is "PTS" for points
    rewards and the tenant base currency for cashback.
    """

    rule_id: UUID
    name: str
    description: str | None = None
    reward_type: str
    reward_value: Decimal
    currency: str
    status: Literal["locked", "in_progress", "earned"]
    progress: RewardProgressOut


class RecentRewardOut(BaseModel):
    """One reward the user has already earned — `GET /me/rewards` recent feed.

    `seen` is True once the mobile client has acknowledged the reward (via
    `POST /me/rewards/seen`), driving the "new reward" badge.
    """

    reward_event_id: UUID
    rule_name: str
    reward_type: str
    value: Decimal
    currency: str
    earned_at: datetime
    seen: bool


class RewardsOut(BaseModel):
    """Signed-in user's rewards view — `GET /me/rewards`.

    `enabled` is False for a `wallet`-mode tenant (no rewards engine), in which
    case `catalog` and `recent` are empty. Otherwise `catalog` lists the active
    rules the user is eligible for with progress, and `recent` the latest firings.

    `referral_code` is the caller's own shareable code, surfaced regardless of
    `enabled` (sharing a code is independent of the rewards catalog). It is null
    for older users created before referral codes existed.
    """

    enabled: bool
    referral_code: str | None = None
    catalog: list[RewardCatalogItemOut]
    recent: list[RecentRewardOut]


class MarkRewardsSeenIn(BaseModel):
    """Body for `POST /me/rewards/seen` — the reward_events to acknowledge."""

    reward_event_ids: list[UUID]


class WalletTransactionOut(BaseModel):
    """One transaction row surfaced on /me/wallet — same data the mobile
    app shows in its recent-activity feed.

    `direction` is derived from the ledger entry on one of the caller's
    own accounts: CREDIT → "in" (money/points arrived), DEBIT → "out".
    `counterparty_name` names the OTHER side of the transaction, and is now
    always populated — a transaction has two sides and a statement row should
    be able to name both. It resolves in descending specificity:

      1. the other party's display name when that side is a user-owned account
         (p2p, merchant_cashin, cash_in, cashout) — a merchant's business name,
         else the person's full name;
      2. what the account IS, when the other side has no owning user (a system
         pool, a bank mirror, a merchant collection account) — e.g. "Cash float"
         or "Bank mirror · Primary";
      3. the caller's OWN other wallet, when every leg belongs to them — a
         commission disbursement moves between two of their own wallets, so
         the counterparty is "Commission wallet".

    Before this, cases 2 and 3 rendered an empty cell. It is never a service
    name; `transaction_type` already carries that.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # Customer-facing reference `S_<YYYYMMDDHHMMSS><NNNNNN>`. Null only for the
    # legacy window before a row was backfilled; always set on new transactions.
    reference: str | None = None
    transaction_type: str
    # The base flow, for grouping and filtering. Equals `transaction_type`
    # unless the transaction was made on a derived service (spec §12.1).
    base_transaction_type: str
    status: str
    # The CALLER'S OWN movement on `wallet_account_id` — never the
    # transaction's headline. A supervisor earning R0.50 of parent commission
    # on a R100 cash-in reads R0.50 here.
    amount: str
    # The transaction's headline principal, kept separate so it can never
    # stand in for `amount` again.
    transaction_amount: str = "0"
    # Which of the caller's wallets moved. One transaction yields one row PER
    # wallet it touches, so an agent's cash-in produces a main-wallet row for
    # what they paid and a commission-wallet row for what they earned.
    wallet_account_id: UUID | None = None
    wallet_account_type: str | None = None
    wallet_label: str | None = None
    fee_amount: str
    # Display-only charge siblings (Epic 20): the commission paid to an agent and
    # the tax collected on this transaction. These are PER-PARTY figures — each is
    # shown only to the party it actually affected (see `_build_recent_txns_payload`),
    # so a counterparty who neither paid nor earned the amount sees "0".
    commission_amount: str = "0"
    tax_amount: str = "0"
    currency: str
    created_at: datetime
    direction: Literal["in", "out"]
    counterparty_name: str | None = None
    # The two principals, populated ONLY when the caller is a THIRD PARTY to
    # the transaction. A supervisor earns parent commission from a transaction
    # between their agent and a customer and is neither side, so a single
    # counterparty cannot express it — the row reads "agent -> customer".
    # Null whenever the caller is one of the two sides.
    sender_name: str | None = None
    receiver_name: str | None = None


class AdminUserTransactionOut(WalletTransactionOut):
    """One transaction row on the ADMIN user-detail page.

    Same shape as the user-facing feed plus `counterparty_phone`, which an
    operator needs to trace a transfer. Kept as a separate model rather than
    an optional field on `WalletTransactionOut` so the user-facing endpoint
    CANNOT serialise the phone even if the payload builder supplies it — one
    customer must never be handed another customer's number.
    """

    counterparty_phone: str | None = None


class AdminUserTransactionsPage(BaseModel):
    """One page of a user's transactions plus the total matching count.

    An envelope rather than a bare list because the admin panel pages 20 at a
    time and needs the total to render "1-20 of N" and disable Next on the
    last page. `total` counts rows matching the SAME filters as `items`.
    """

    items: list[AdminUserTransactionOut]
    total: int


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
    """Request body for `POST /identity/otp/send`.

    `referral_code` is an OPTIONAL referrer's code captured at mobile signup.
    It is used ONLY when this OTP auto-registers a NEW phone (Pay-PRD-0010): the
    new user is created WITH the code, creating the `referrals` row and firing
    any active signup-trigger referral rule. For an EXISTING phone it is ignored
    (an OTP re-request must never alter an established user). Absent / null →
    organic signup, no referral.
    """

    tenant_id: UUID
    phone: str = Field(min_length=5, max_length=20)
    referral_code: str | None = Field(default=None, min_length=1, max_length=16)

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
