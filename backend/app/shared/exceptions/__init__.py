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


# --- Tenants ----------------------------------------------------------------


class TenantNotFound(AppHTTPException):
    """The provided tenant_id does not exist or is inactive."""

    def __init__(self) -> None:
        super().__init__(404, "tenant_not_found", "Tenant not found.")


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
        super().__init__(
            404, "provider_not_found", "Redemption provider not found."
        )


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
        super().__init__(
            404, "redemption_not_found", "Redemption not found."
        )


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
        super().__init__(
            401, "invalid_credentials", "Phone or PIN is incorrect."
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
    """PIN doesn't meet the 4–6 digit numeric format."""

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
