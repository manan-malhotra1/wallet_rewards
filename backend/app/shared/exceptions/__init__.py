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

    Owner-facing (e.g. a top-up to your own wallet). `window` is
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


class BudgetNotFound(AppHTTPException):
    """The referenced budget row doesn't exist or belongs to a different tenant."""

    def __init__(self) -> None:
        super().__init__(404, "budget_not_found", "Budget not found.")


class LimitConfigNotFound(AppHTTPException):
    """The referenced limit config row doesn't exist or belongs to a different tenant."""

    def __init__(self) -> None:
        super().__init__(404, "limit_config_not_found", "Limit config not found.")


class WalletLimitConfigNotFound(AppHTTPException):
    """The wallet limit config row doesn't exist or belongs to a different tenant."""

    def __init__(self) -> None:
        super().__init__(404, "wallet_limit_config_not_found", "Wallet limit config not found.")


class PricingConfigNotFound(AppHTTPException):
    """The referenced pricing config row doesn't exist or belongs to a different tenant."""

    def __init__(self) -> None:
        super().__init__(404, "pricing_config_not_found", "Pricing config not found.")


class CommissionConfigNotFound(AppHTTPException):
    """The referenced commission config row doesn't exist or belongs to another tenant."""

    def __init__(self) -> None:
        super().__init__(404, "commission_config_not_found", "Commission config not found.")


class TaxConfigNotFound(AppHTTPException):
    """The referenced tax config row doesn't exist or belongs to another tenant."""

    def __init__(self) -> None:
        super().__init__(404, "tax_config_not_found", "Tax config not found.")


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


class StepUpPolicyNotFound(AppHTTPException):
    """The referenced step-up policy doesn't exist or belongs to another tenant."""

    def __init__(self) -> None:
        super().__init__(404, "step_up_policy_not_found", "Step-up policy not found.")


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
