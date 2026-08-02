"""Custom HTTP exception classes.

All exceptions raised from services should subclass `AppHTTPException`. The
FastAPI exception handler converts them into the standard error envelope:

    { "error_code": "...", "message": "..." }

Never include PII, stack traces, or internal IDs in the message — see
NFR-0170 and `.claude/rules/compliance-fintech.md`.
"""

from __future__ import annotations

from fastapi import HTTPException


class AppHTTPException(HTTPException):
    """Base class for all app-defined HTTP exceptions.

    Args:
        status_code: HTTP status (e.g. 404, 409, 422).
        error_code: Stable machine-readable code (e.g. "user_not_found").
        message: Human-readable summary safe for API consumers.
    """

    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(
            status_code=status_code,
            detail={"error_code": error_code, "message": message},
        )


# --- Identity ---------------------------------------------------------------


class UserNotFound(AppHTTPException):
    """No user found for the resolved identifier in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "user_not_found", "No user found for that identifier.")


class IdentifierAlreadyInUse(AppHTTPException):
    """An identifier already maps to a different user in this tenant (Pay-PRD-0070)."""

    def __init__(self, identifier_type: str) -> None:
        super().__init__(
            409,
            "identifier_already_in_use",
            f"This {identifier_type} is already registered to another user.",
        )


class IdentifierNotManuallyVerifiable(AppHTTPException):
    """The identifier's type cannot be verified by an admin (Epic 27, Story 27.3).

    Only `account_number` identifiers have a manual admin-verification path.
    phone / email are verification-proven through the OTP flow, and `card_number`
    is never stored as a plain identifier — so all of those are rejected here.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "identifier_not_manually_verifiable",
            "Only account-number identifiers can be verified by an admin; "
            "phone/email use OTP.",
        )


class InvalidUserTypeParent(AppHTTPException):
    """The parent_user_id is incompatible with the user's type (Decision D4, Epic 12).

    Raised when a consumer/super_agent/head_merchant is given a parent, or an
    agent/merchant's supplied parent is missing, in another tenant, or not the
    required parent type (super_agent for agent, head_merchant for merchant).
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "user_type_invalid_parent",
            "The parent user is not compatible with this user type.",
        )


# --- Admin access-lock (user.status enforcement, migration 0045) ------------


class AccountSuspended(AppHTTPException):
    """Login refused because the account is login-locked (status suspended/closed).

    Raised by `authenticate_pin` BEFORE PIN verification: a locked account should
    never reach credential checking. Deliberately generic — the same message
    covers `suspended` and `closed` so the caller learns nothing beyond "locked".
    """

    def __init__(self) -> None:
        super().__init__(
            403,
            "account_suspended",
            "This account is locked. Contact support.",
        )


class TransactionsBlocked(AppHTTPException):
    """A user-initiated money path was attempted on a non-active account.

    Raised by `assert_user_can_transact` at the top of every user-initiated money
    path (P2P send, cash-out, cash-in, airtime, redemption, change-PIN) when the
    acting user's status is not `active` (txn_locked, suspended, or closed). The
    receiving side of a transfer is passive and is NOT blocked.
    """

    def __init__(self) -> None:
        super().__init__(
            403,
            "transactions_blocked",
            "Transactions are locked on this account.",
        )


# --- Tenants ----------------------------------------------------------------


class TenantNotFound(AppHTTPException):
    """The provided tenant_id does not exist or is inactive."""

    def __init__(self) -> None:
        super().__init__(404, "tenant_not_found", "Tenant not found.")


class ServiceNotFound(AppHTTPException):
    """The given service_id doesn't map to a live row in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "service_not_found", "Service not found.")


class AccountAlreadyExists(AppHTTPException):
    """Another account already covers this (tenant, user, type, currency)
    tuple — or (tenant, type, currency) for system-owned accounts.

    Raised when the partial UNIQUE index `uq_accounts_user_scoped` /
    `uq_accounts_system_scoped` would be violated. Surfaces as 409 so
    callers can treat it as an idempotent no-op rather than a 500.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "account_already_exists",
            "An account with this (tenant, user, type, currency) already exists.",
        )


class BankMirrorNameAlreadyExists(AppHTTPException):
    """Another bank mirror already uses this name for the (tenant, currency).

    Bank mirrors are `operator_adjustment` accounts; several coexist per
    (tenant, currency) but each name must be unique (partial UNIQUE index
    `uq_accounts_bank_mirror`). Surfaces as 409 rather than a raw IntegrityError.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "bank_mirror_name_already_exists",
            "A bank mirror with this name already exists for this currency.",
        )


class InstrumentNotFound(AppHTTPException):
    """The given instrument_id doesn't map to a live row in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "instrument_not_found", "Instrument not found.")


class InstrumentCodeAlreadyExists(AppHTTPException):
    """Another live instrument in this tenant already uses this code.

    Raised by the Phase 3 catalog create flow. Codes are unique per tenant
    via the partial UNIQUE index `uq_instruments_tenant_code_alive`.
    """

    def __init__(self, code: str) -> None:
        super().__init__(
            409,
            "instrument_code_already_exists",
            f"An instrument with code '{code}' already exists for this tenant.",
        )


class ServiceCodeAlreadyExists(AppHTTPException):
    """Another live service in this tenant already uses this code.

    Raised by the Phase 2 catalog create flow. Codes are unique per tenant
    (partial UNIQUE index `uq_services_tenant_code_alive`), and the UI
    surfaces the 409 with a "code already in use" message.
    """

    def __init__(self, code: str) -> None:
        super().__init__(
            409,
            "service_code_already_exists",
            f"A service with code '{code}' already exists for this tenant.",
        )


class TenantNameAlreadyExists(AppHTTPException):
    """Another tenant already holds this name.

    Raised by the Phase 1 tenant-rename flow: tenant names are globally
    unique (UNIQUE constraint on tenants.name) and updates must surface a
    clean 409 instead of letting the IntegrityError bubble.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            409,
            "tenant_name_already_exists",
            f"A tenant named '{name}' already exists.",
        )


# --- Accounts ---------------------------------------------------------------


class AccountNotFound(AppHTTPException):
    """No account with the given id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "account_not_found", "Account not found.")


class InvalidAccountType(AppHTTPException):
    """An unsupported account_type was supplied."""

    def __init__(self) -> None:
        super().__init__(
            422, "invalid_account_type", "Account type is not one of the allowed values."
        )


# --- Ledger -----------------------------------------------------------------


class UnbalancedTransaction(AppHTTPException):
    """The ledger entries on a transaction do not sum to zero (NFR-0100)."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "unbalanced_transaction",
            "Debits and credits must sum to zero.",
        )


class DuplicateIdempotencyKey(AppHTTPException):
    """The idempotency key was reused with a different payload.

    Per Pay-PRD-0200, identical replays return the original transaction;
    this exception is raised only when the replay has a CONFLICTING body.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "idempotency_conflict",
            "Idempotency key already used with a different request body.",
        )


# --- Payments ---------------------------------------------------------------


class InsufficientFunds(AppHTTPException):
    """Sender's available balance is less than the requested amount (Pay-PRD-0220)."""

    def __init__(self) -> None:
        super().__init__(
            409,
            "insufficient_funds",
            "The sender's available balance is insufficient for this transfer.",
        )


class InsufficientFloat(AppHTTPException):
    """A float-sourced funding would drive the operator cash float below zero.

    The cash float (`system_cash_inflow`) is a POSITIVE balance that must be
    topped up from the bank (via `treasury.adjust_system_wallet`) BEFORE it can
    fund users. Any net DEBIT of the float that would overdraw it is rejected at
    `post_transaction`'s balance guard (invariant #11) BEFORE any ledger write.

    Distinct from `InsufficientFunds` (a user financial_wallet overdraft): this
    tells the operator to replenish the float, not the user to top up.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "insufficient_float",
            "Operator cash float is insufficient — top up the float from the bank first.",
        )


class FundingTemporarilyUnavailable(AppHTTPException):
    """Partner-facing masked error for an operator-side funding shortfall.

    The `insufficient_float` message is operator-internal (it names the float and
    tells the operator to replenish from the bank). Exposing it to an external
    API partner would leak the operator's liquidity state + remediation for a
    condition entirely outside the partner's control (security review, Low). The
    external funding path maps `InsufficientFloat` to this generic, retryable
    503 instead; the specific error stays on the admin/treasury surfaces.
    """

    def __init__(self) -> None:
        super().__init__(
            503,
            "funding_temporarily_unavailable",
            "Funding is temporarily unavailable. Please retry later.",
        )


class NothingToWithdraw(AppHTTPException):
    """A withdraw_all was requested but the wallet has no available balance."""

    def __init__(self) -> None:
        super().__init__(
            409,
            "nothing_to_withdraw",
            "The wallet has no available balance to withdraw.",
        )


class CurrencyMismatch(AppHTTPException):
    """Sender and recipient wallets are in different currencies.

    Phase 1 does not perform FX conversion (PRD §5 non-goal). The transaction's
    currency must match both account currencies.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "currency_mismatch",
            "Sender and recipient accounts must hold the same currency.",
        )


class SelfTransferNotAllowed(AppHTTPException):
    """A user cannot transfer funds to themselves.

    Not explicitly in the PRD, but a sane invariant — self-transfer is a no-op
    that pollutes the ledger and confuses balance derivation.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "self_transfer_not_allowed",
            "Cannot transfer funds to the same user.",
        )


class RecipientNotAgent(AppHTTPException):
    """Cash-out target is not an agent (or super-agent).

    A subscriber may only cash out TO an agent — the mirror of agent cash-in.
    Resolving the identifier to a non-agent recipient is a client error (422),
    not a "not found": the user exists, they just aren't an eligible cash-out
    counterparty.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "recipient_not_agent",
            "Cash-out recipient must be an agent.",
        )


# --- Events & Rules ---------------------------------------------------------


class SourceNotRegistered(AppHTTPException):
    """The event's source_key is not registered in `external_event_sources`."""

    def __init__(self) -> None:
        super().__init__(
            404,
            "source_not_registered",
            "Event source is not registered.",
        )


class SourceKeyAlreadyInUse(AppHTTPException):
    """Attempt to register a source_key that already exists globally."""

    def __init__(self) -> None:
        super().__init__(
            409,
            "source_key_already_in_use",
            "Another source is already registered with this source_key.",
        )


class SourceTenantMismatch(AppHTTPException):
    """Event's tenant_id does not match the registered source's tenant_id."""

    def __init__(self) -> None:
        super().__init__(
            403,
            "source_tenant_mismatch",
            "Event tenant does not match registered source tenant.",
        )


class RuleNotFound(AppHTTPException):
    """No rule with the given id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "rule_not_found", "Rule not found.")


class InvalidRuleConfig(AppHTTPException):
    """A rule's fields are inconsistent (e.g. milestone without count_threshold)."""

    def __init__(self, detail: str) -> None:
        super().__init__(422, "invalid_rule_config", detail)


class UserPointsAccountMissing(AppHTTPException):
    """User has no points_account in this tenant — cannot issue points rewards."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "user_points_account_missing",
            "Recipient user does not have a points account.",
        )


class SystemPointsIssuanceMissing(AppHTTPException):
    """Tenant has no system_points_issuance account — cannot issue points rewards."""

    def __init__(self) -> None:
        super().__init__(
            500,
            "system_points_issuance_missing",
            "Tenant is missing its system_points_issuance account.",
        )


class UserFinancialWalletMissing(AppHTTPException):
    """User has no financial_wallet in this currency — cannot issue cashback rewards."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "user_financial_wallet_missing",
            "Recipient user does not have a wallet in this currency.",
        )


# --- Referrals (Epic 10 / WAL-77) -------------------------------------------


class InvalidReferralCode(AppHTTPException):
    """The referral code quoted at signup does not resolve in this tenant."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "invalid_referral_code",
            "The referral code is not valid.",
        )


class SelfReferralNotAllowed(AppHTTPException):
    """A user cannot refer themselves (the code resolves to the same user)."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "self_referral_not_allowed",
            "You cannot use your own referral code.",
        )


# --- Redemption -------------------------------------------------------------


class RedemptionProviderNotFound(AppHTTPException):
    """No redemption provider with the given id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "provider_not_found", "Redemption provider not found.")


class RedemptionProviderInactive(AppHTTPException):
    """Provider exists but is inactive — cannot accept new redemptions."""

    def __init__(self) -> None:
        super().__init__(
            409,
            "provider_inactive",
            "Redemption provider is inactive.",
        )


class RedemptionNotFound(AppHTTPException):
    """No redemption with the given id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "redemption_not_found", "Redemption not found.")


class RedemptionNotPending(AppHTTPException):
    """Caller tried to confirm/fail a redemption that's no longer PENDING.

    Terminal statuses (COMPLETED, FAILED, REVERSED) are final.
    """

    def __init__(self, current_status: str) -> None:
        super().__init__(
            409,
            "redemption_not_pending",
            f"Redemption is in status {current_status}, cannot transition.",
        )


# --- Reconciliation ---------------------------------------------------------


class RedemptionNotInManualReview(AppHTTPException):
    """Manual resolve was called on a redemption that's not in MANUAL_REVIEW."""

    def __init__(self, current_status: str) -> None:
        super().__init__(
            409,
            "redemption_not_in_manual_review",
            (
                f"Redemption is in status {current_status}; manual resolve only "
                "permitted when status is MANUAL_REVIEW."
            ),
        )


class InvalidResolveOutcome(AppHTTPException):
    """Manual resolve outcome wasn't one of COMPLETED or REVERSED."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "invalid_resolve_outcome",
            "Outcome must be COMPLETED or REVERSED.",
        )


# --- Auth (Phase F.1) -------------------------------------------------------


class InvalidAuthorizationHeader(AppHTTPException):
    """Missing or malformed Authorization header (Bearer scheme expected)."""

    def __init__(self, detail: str = "Missing or malformed Authorization header.") -> None:
        super().__init__(401, "invalid_authorization_header", detail)


class InvalidToken(AppHTTPException):
    """JWT signature failed, header malformed, or claims invalid."""

    def __init__(self, detail: str = "Token validation failed.") -> None:
        super().__init__(401, "invalid_token", detail)


class InvalidAlgorithm(AppHTTPException):
    """Token alg is 'none' or outside the RS256 whitelist."""

    def __init__(self, alg: str) -> None:
        super().__init__(
            401,
            "invalid_algorithm",
            f"Token algorithm '{alg}' is not accepted.",
        )


class TokenExpired(AppHTTPException):
    """JWT `exp` claim is in the past."""

    def __init__(self) -> None:
        super().__init__(401, "token_expired", "Token has expired.")


class UnknownSigningKey(AppHTTPException):
    """The `kid` in the token header doesn't match any key in the realm's JWKS."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "unknown_signing_key",
            "Token was signed with an unrecognised key.",
        )


class InsufficientRole(AppHTTPException):
    """The authenticated principal doesn't hold the required realm role."""

    def __init__(self, required: str) -> None:
        super().__init__(
            403,
            "insufficient_role",
            f"This action requires the '{required}' role.",
        )


# --- PIN / OTP / Session (Phase F.2) ---------------------------------------


class OtpRateLimited(AppHTTPException):
    """Too many OTP-send requests for this phone within the window."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            429,
            "otp_rate_limited",
            f"Too many OTP requests. Try again in {retry_after} seconds.",
        )


class RateLimited(AppHTTPException):
    """Per-key request quota exceeded on the external API (Epic 14)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            429,
            "rate_limited",
            f"Rate limit exceeded. Try again in {retry_after} seconds.",
        )


class InvalidOtp(AppHTTPException):
    """OTP wrong, expired, already used, or no active OTP for this phone.

    Intentionally identical message for all four — we never reveal which.
    """

    def __init__(self) -> None:
        super().__init__(401, "invalid_otp", "OTP is invalid or has expired.")


class OtpExpired(AppHTTPException):
    """OTP exists but is past its expiry. Same surfaced error as InvalidOtp
    when the verifier sees a single failed branch, but here for clarity in
    code paths that explicitly check expiry first."""

    def __init__(self) -> None:
        super().__init__(401, "otp_expired", "OTP has expired.")


class InvalidRegistrationToken(AppHTTPException):
    """Token from /otp/verify is missing, expired, or already consumed."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "invalid_registration_token",
            "Registration token is invalid or has expired.",
        )


class PinAlreadySet(AppHTTPException):
    """User already has a PIN — use PIN reset flow instead (deferred)."""

    def __init__(self) -> None:
        super().__init__(
            409,
            "pin_already_set",
            "PIN is already set. Use PIN reset flow to change it.",
        )


class PinNotSet(AppHTTPException):
    """User exists but has no PIN — caller must complete registration first."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "pin_not_set",
            "No PIN configured for this account.",
        )


class InvalidCredentials(AppHTTPException):
    """PIN doesn't match. Generic message — never leak which side was wrong."""

    def __init__(self) -> None:
        super().__init__(401, "invalid_credentials", "Phone or PIN is incorrect.")


class NewPinSameAsCurrent(AppHTTPException):
    """Change-PIN was asked to set the new PIN equal to the current one.

    A no-op that would still charge a fee — rejected before any charge or
    ledger work. Deliberately does NOT confirm the current PIN was correct
    (this is checked earlier); it only reports that the values are identical.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "new_pin_same_as_current",
            "New PIN must differ from the current PIN.",
        )


class AccountLocked(AppHTTPException):
    """Too many failed PIN attempts. Locked for `retry_after` seconds (NFR-0190)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            423,
            "account_locked",
            f"Account locked. Try again in {retry_after} seconds.",
        )


class InvalidSession(AppHTTPException):
    """Session token is missing, unknown, or expired."""

    def __init__(self) -> None:
        super().__init__(401, "invalid_session", "Session is invalid or has expired.")


class InvalidPinFormat(AppHTTPException):
    """PIN doesn't meet the 4-6 digit numeric format."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "invalid_pin_format",
            "PIN must be 4 to 6 numeric digits.",
        )


# --- Roles & Permissions (Phase F.3 / Module 7) ----------------------------


class RoleNotFound(AppHTTPException):
    """No role with the given id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "role_not_found", "Role not found.")


class RoleAlreadyExists(AppHTTPException):
    """Duplicate (tenant_id, name) — role names are unique within a tenant."""

    def __init__(self, name: str) -> None:
        super().__init__(
            409,
            "role_already_exists",
            f"A role named '{name}' already exists in this tenant.",
        )


class NotAuthorised(AppHTTPException):
    """The user has no active role permitting this transaction_type.

    Step 1 of the Pay-PRD-0260 orchestration sequence (Pay-PRD-0440 / 0450 /
    0460). Rejected BEFORE any limits / pricing / ledger evaluation.
    """

    def __init__(self, transaction_type: str) -> None:
        super().__init__(
            403,
            "not_authorised",
            f"You are not authorised to initiate a '{transaction_type}' transaction.",
        )


# --- Per-service access policy (services.allowed_user_types / _channels) -----


class ServiceNotAllowedForUserType(AppHTTPException):
    """The acting user's `user_type` is not on the service's `allowed_user_types`.

    Enforces the WHO dimension of the per-service access policy so the API
    rejects exactly what the mobile app hides (what is DISPLAYED == what is
    ALLOWED). A distinct code from `ServiceNotAllowedOnChannel` lets the client
    tell the two rejection dimensions apart. Raised BEFORE any ledger work.
    """

    def __init__(self) -> None:
        super().__init__(
            403,
            "service_not_allowed_user_type",
            "Your account type is not permitted to use this service.",
        )


class ServiceNotAllowedOnChannel(AppHTTPException):
    """The initiating channel is not on the service's `allowed_channels`.

    Enforces the HOW dimension of the per-service access policy (e.g. an
    operator-only service reached over the wrong surface). Distinct code from
    `ServiceNotAllowedForUserType`. Raised BEFORE any ledger work.
    """

    def __init__(self) -> None:
        super().__init__(
            403,
            "service_not_allowed_channel",
            "This service is not available on this channel.",
        )


# --- HMAC / provider callbacks (Phase F.5) ---------------------------------


class SignatureMissing(AppHTTPException):
    """X-Sasai-Signature header missing on a callback that requires one."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "signature_missing",
            "X-Sasai-Signature header is required.",
        )


class SignatureMalformed(AppHTTPException):
    """Signature header present but not parseable (missing t= or v1=)."""

    def __init__(self, detail: str = "Signature header is malformed.") -> None:
        super().__init__(401, "signature_malformed", detail)


class SignatureTimestampSkew(AppHTTPException):
    """Signature timestamp is outside the 5-minute replay window (NFR-0210)."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "signature_timestamp_skew",
            "Signature timestamp is outside the allowed window.",
        )


class InvalidSignature(AppHTTPException):
    """HMAC verification failed — body tampered, secret wrong, or replay."""

    def __init__(self) -> None:
        super().__init__(401, "invalid_signature", "Signature verification failed.")


class SignatureNotConfigured(AppHTTPException):
    """Provider has no `shared_secret` set — callbacks are not enabled."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "signature_not_configured",
            "Provider has no callback secret configured.",
        )


class ApiKeyInvalid(AppHTTPException):
    """External-API key is unknown, revoked, or missing (Epic 14).

    Deliberately vague — an unknown key and a revoked key return the same
    response so an attacker can't enumerate valid key_ids (NFR-0220).
    """

    def __init__(self) -> None:
        super().__init__(401, "api_key_invalid", "API key is invalid or revoked.")


class ApiKeyNotFound(AppHTTPException):
    """No API key with that id in this tenant (e.g. revoke target missing)."""

    def __init__(self) -> None:
        super().__init__(404, "api_key_not_found", "API key not found.")


class NotAMerchantKey(AppHTTPException):
    """The authenticated API key is not bound to a merchant (merchant_cashin).

    `merchant_cashin` funds a consumer from the merchant's own wallet, so the
    calling key must carry `merchant_user_id`. An ordinary partner key (used for
    fund/withdraw) cannot initiate it.
    """

    def __init__(self) -> None:
        super().__init__(
            403,
            "not_a_merchant_key",
            "This API key is not authorised to initiate a merchant cash-in.",
        )


class MerchantUserRequired(AppHTTPException):
    """The `merchant_user_id` supplied at key creation is not a valid merchant.

    Raised when minting an API key with a `merchant_user_id` that either does
    not exist in the tenant or resolves to a non-merchant user type. Both cases
    collapse to one 422 so key creation never leaks user existence across the
    admin boundary. This is distinct from `NotAMerchantKey` (the auth-time 403
    for calling merchant-cashin with a non-merchant key).
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "merchant_user_required",
            "merchant_user_id must reference a merchant-type user in this tenant.",
        )


# --- Money controls (Phase G) ----------------------------------------------


class BudgetExceeded(AppHTTPException):
    """A reward issuance would exceed the configured budget cap (WAL-50)."""

    def __init__(self, window_type: str) -> None:
        super().__init__(
            409,
            "budget_exceeded",
            f"Reward budget exhausted for window '{window_type}'.",
        )


class AmountBelowMin(AppHTTPException):
    """Transaction amount is below the configured min (WAL-51)."""

    def __init__(self, min_amount: str) -> None:
        super().__init__(
            422,
            "amount_below_min",
            f"Amount must be at least {min_amount}.",
        )


class AmountAboveMax(AppHTTPException):
    """Transaction amount exceeds the configured max (WAL-51)."""

    def __init__(self, max_amount: str) -> None:
        super().__init__(
            422,
            "amount_above_max",
            f"Amount must not exceed {max_amount}.",
        )


class DailyCountExceeded(AppHTTPException):
    """User has already hit the per-24h transaction count cap (WAL-51)."""

    def __init__(self, cap: int) -> None:
        super().__init__(
            429,
            "daily_count_exceeded",
            f"Daily transaction count of {cap} already reached.",
        )


class DailyValueExceeded(AppHTTPException):
    """This transaction would push the rolling-24h value past the cap (WAL-51)."""

    def __init__(self, cap: str) -> None:
        super().__init__(
            429,
            "daily_value_exceeded",
            f"Daily value cap of {cap} would be exceeded.",
        )


class WeeklyCountExceeded(AppHTTPException):
    """User has already hit the rolling-7d transaction count cap (WAL-234)."""

    def __init__(self, cap: int) -> None:
        super().__init__(
            429,
            "weekly_count_exceeded",
            f"Weekly transaction count of {cap} already reached.",
        )


class WeeklyValueExceeded(AppHTTPException):
    """This transaction would push the rolling-7d value past the cap (WAL-234)."""

    def __init__(self, cap: str) -> None:
        super().__init__(
            429,
            "weekly_value_exceeded",
            f"Weekly value cap of {cap} would be exceeded.",
        )


class MonthlyCountExceeded(AppHTTPException):
    """User has already hit the rolling-30d transaction count cap (WAL-234)."""

    def __init__(self, cap: int) -> None:
        super().__init__(
            429,
            "monthly_count_exceeded",
            f"Monthly transaction count of {cap} already reached.",
        )


class MonthlyValueExceeded(AppHTTPException):
    """This transaction would push the rolling-30d value past the cap (WAL-234)."""

    def __init__(self, cap: str) -> None:
        super().__init__(
            429,
            "monthly_value_exceeded",
            f"Monthly value cap of {cap} would be exceeded.",
        )


class WalletSendLimitExceeded(AppHTTPException):
    """A cumulative wallet SEND cap would be breached (WAL-235).

    Spans every service for the user's financial wallet (not per
    transaction_type). `window` is daily/weekly/monthly and `axis` is
    count/value, yielding error codes like `wallet_send_weekly_value_exceeded`.
    """

    def __init__(self, window: str, axis: str, cap: str) -> None:
        super().__init__(
            429,
            f"wallet_send_{window}_{axis}_exceeded",
            f"Wallet {window} send {axis} cap of {cap} would be exceeded.",
        )


class WalletReceiveLimitExceeded(AppHTTPException):
    """A cumulative wallet RECEIVE cap would be breached (WAL-236).

    Owner-facing (e.g. a fund to your own wallet). `window` is
    daily/weekly/monthly and `axis` is count/value, yielding codes like
    `wallet_receive_monthly_count_exceeded`.
    """

    def __init__(self, window: str, axis: str, cap: str) -> None:
        super().__init__(
            429,
            f"wallet_receive_{window}_{axis}_exceeded",
            f"Wallet {window} receive {axis} cap of {cap} would be exceeded.",
        )


class MaxBalanceExceeded(AppHTTPException):
    """A credit would push the wallet past its max-balance ceiling (WAL-236).

    Owner-facing — the account holder is told their own cap.
    """

    def __init__(self, cap: str) -> None:
        super().__init__(
            409,
            "max_balance_exceeded",
            f"Wallet max balance of {cap} would be exceeded.",
        )


class RecipientLimitReached(AppHTTPException):
    """A P2P transfer would breach the RECIPIENT's receive cap (WAL-236).

    Sender-facing and deliberately detail-free: the recipient is not notified
    and no recipient state (which cap, current balance) is leaked.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "recipient_limit_reached",
            "Recipient cannot receive this transfer right now.",
        )


class RecipientMaxBalanceExceeded(AppHTTPException):
    """A P2P transfer would push the RECIPIENT past their max balance (WAL-236).

    Sender-facing and detail-free (see `RecipientLimitReached`).
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "recipient_max_balance_exceeded",
            "Recipient cannot receive this transfer.",
        )


class PricingConfigMissing(AppHTTPException):
    """No pricing config for this (tenant, txn-type, account, currency) (WAL-52).

    Per Pay-PRD-0420 every transaction must run pricing — operators have
    to explicitly configure zero-fee if that's the intent. Silent
    pass-through is forbidden.
    """

    def __init__(self, transaction_type: str) -> None:
        super().__init__(
            422,
            "pricing_config_missing",
            f"No pricing config exists for '{transaction_type}' in this tenant.",
        )


class ServiceNotConfigured(AppHTTPException):
    """A money path was tried while lacking pricing OR limit config (Epic 23, invariant #12).

    UNCONDITIONAL fail-closed gate: every money path may run only if BOTH a
    pricing config and a limit config resolve for the acting user's type. This is
    raised (before any ledger work) when either is missing, naming the service
    and the resolved user_type.
    """

    def __init__(self, service: str, user_type: str) -> None:
        super().__init__(
            422,
            "service_not_configured",
            f"Service '{service}' is not fully configured for user type "
            f"'{user_type}' in this tenant (pricing and limits are both required).",
        )


class BudgetNotFound(AppHTTPException):
    """The referenced budget row doesn't exist or belongs to a different tenant."""

    def __init__(self) -> None:
        super().__init__(404, "budget_not_found", "Budget not found.")


# --- Config governance: maker-checker (Pricing v2 Epic 22) ------------------


class SelfApprovalForbidden(AppHTTPException):
    """A maker tried to approve or review their own config-change request.

    Four-eyes (separation of duties): the checker MUST be a different admin than
    the maker who proposed the change.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "self_approval_forbidden",
            "The checker must be a different admin than the maker.",
        )


class ConfigRequestNotFound(AppHTTPException):
    """No config-change request with that id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "config_request_not_found", "Config change request not found.")


class ConfigRequestInvalidState(AppHTTPException):
    """The request isn't in a state that permits this action.

    E.g. approving a non-PENDING request, or revising one that isn't in
    CHANGES_REQUESTED. The message names the current status.
    """

    def __init__(self, current_status: str) -> None:
        super().__init__(
            409,
            "config_request_invalid_state",
            f"Request is in status {current_status}; this action is not permitted.",
        )


class ConfigRequestForbidden(AppHTTPException):
    """The admin isn't allowed to act on this request (e.g. not the maker)."""

    def __init__(self, detail: str = "You are not permitted to act on this request.") -> None:
        super().__init__(403, "config_request_forbidden", detail)


class ConfigRequestCommentRequired(AppHTTPException):
    """A request-changes action arrived without the mandatory comment."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "config_request_comment_required",
            "A comment is required when requesting changes.",
        )


class ConfigRequestTargetNotFound(AppHTTPException):
    """The `target_config_id` on an update/delete proposal does not exist here.

    Raised at propose time for an update (the live config row the maker wants to
    edit is absent in this tenant for the given config type), and at APPLY time
    for a delete — the target's scope is resolved from the live row when the
    checker approves, so a row gone by then 404s with this same uniform code.
    """

    def __init__(self) -> None:
        super().__init__(
            404,
            "config_request_target_not_found",
            "The target config to edit was not found in this tenant.",
        )


class ConfigRequestAlreadyOpen(AppHTTPException):
    """An OPEN change request already exists for this config scope.

    One in-flight change per (tenant_id, config_type, scope): a maker may not
    stack a second proposal on a scope that already has a PENDING or
    CHANGES_REQUESTED request. The maker must approve, reject, or withdraw the
    open one — or revise it in place — before proposing another change.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "config_request_already_open",
            "A change for this config is already awaiting approval — approve, "
            "reject, or withdraw it first.",
        )


# --- Money-operation maker-checker (Epic 18) -------------------------------


class MoneyOperationNotFound(AppHTTPException):
    """No money-operation request with that id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "money_operation_not_found", "Money operation not found.")


class MoneyOperationInvalidState(AppHTTPException):
    """The money-operation request isn't in a state that permits this action.

    E.g. approving a non-PENDING request, revising one that isn't in
    CHANGES_REQUESTED, or acting on an APPLIED/WITHDRAWN (terminal) request. The
    message names the current status.
    """

    def __init__(self, current_status: str) -> None:
        super().__init__(
            409,
            "money_operation_invalid_state",
            f"Money operation is in status {current_status}; this action is not permitted.",
        )


class MoneyOperationForbidden(AppHTTPException):
    """The admin isn't allowed to act on this request (e.g. not the maker)."""

    def __init__(
        self, detail: str = "You are not permitted to act on this money operation."
    ) -> None:
        super().__init__(403, "money_operation_forbidden", detail)


class MoneyOperationDuplicateApprover(AppHTTPException):
    """This admin already recorded an approval in the current approval round.

    N-eyes needs DISTINCT checkers: the same admin cannot supply two of the
    required approvals. Resubmitting a request resets the round, so a fresh
    approval by the same admin after a resubmit is permitted.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "money_operation_duplicate_approver",
            "This admin already approved this request.",
        )


# --- User-operation maker-checker (admin create/edit user) -----------------


class UserOperationNotFound(AppHTTPException):
    """No user-operation request with that id in this tenant."""

    def __init__(self) -> None:
        super().__init__(404, "user_operation_not_found", "User operation not found.")


class UserOperationInvalidState(AppHTTPException):
    """The user-operation request isn't in a state that permits this action.

    E.g. approving a non-PENDING request, revising one that isn't in
    CHANGES_REQUESTED, or acting on an APPLIED/WITHDRAWN (terminal) request. The
    message names the current status.
    """

    def __init__(self, current_status: str) -> None:
        super().__init__(
            409,
            "user_operation_invalid_state",
            f"User operation is in status {current_status}; this action is not permitted.",
        )


class UserOperationForbidden(AppHTTPException):
    """The admin isn't allowed to act on this request (e.g. not the maker)."""

    def __init__(
        self, detail: str = "You are not permitted to act on this user operation."
    ) -> None:
        super().__init__(403, "user_operation_forbidden", detail)


class UserOperationDuplicateApprover(AppHTTPException):
    """This admin already recorded an approval in the current approval round.

    N-eyes needs DISTINCT checkers: the same admin cannot supply two of the
    required approvals. Resubmitting a request resets the round, so a fresh
    approval by the same admin after a resubmit is permitted.
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "user_operation_duplicate_approver",
            "This admin already approved this request.",
        )


# --- Step-up PIN ----------------------------------------------------------


class StepUpRequired(AppHTTPException):
    """Caller exceeded the step-up threshold but didn't supply a PIN.

    The mobile client should prompt for the user's PIN and retry the
    same request with `pin` in the body.
    """

    def __init__(self, transaction_type: str, threshold: str, currency: str) -> None:
        super().__init__(
            401,
            "step_up_required",
            f"This {transaction_type} exceeds the {currency} {threshold} step-up "
            "threshold. Re-enter your PIN and retry.",
        )


class InvalidStepUpPin(AppHTTPException):
    """PIN supplied for step-up did not match the user's stored hash."""

    def __init__(self) -> None:
        super().__init__(401, "invalid_step_up_pin", "Incorrect PIN. Please try again.")


# --- Airtime recharge ----------------------------------------------------


class AirtimeMerchantNotConfigured(AppHTTPException):
    """No active airtime merchant is configured for this tenant (Epic 17)."""

    def __init__(self) -> None:
        super().__init__(
            422,
            "airtime_merchant_not_configured",
            "No active airtime merchant is configured for this tenant.",
        )


class AirtimeRechargeNotFound(AppHTTPException):
    """Unknown airtime_recharge_id, or one belonging to another tenant."""

    def __init__(self) -> None:
        super().__init__(404, "airtime_recharge_not_found", "Airtime recharge not found.")


class AirtimeRechargeAlreadySettled(AppHTTPException):
    """Tried to confirm/fail an airtime recharge that is no longer PENDING."""

    def __init__(self, current_status: str) -> None:
        super().__init__(
            409,
            "airtime_recharge_already_settled",
            f"Airtime recharge already in terminal state '{current_status}'.",
        )


# --- Analytics -------------------------------------------------------------


class InvalidAnalyticsParameter(AppHTTPException):
    """Raised when an analytics `range`/`granularity` query param is unrecognised.

    Surfaces as HTTP 422 so a bad client parameter never masks a genuine
    server-side ValueError elsewhere in the app (e.g. internal `raise ValueError`
    guards in budgets/service or rules/evaluator would otherwise be caught by an
    app-global ValueError handler and mis-reported as client 422s).
    """

    def __init__(self, message: str) -> None:
        super().__init__(422, "invalid_parameter", message)
