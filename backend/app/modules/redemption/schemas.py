"""Pydantic v2 schemas for the redemption module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProviderRegistrationRequest(BaseModel):
    """Admin request to register a redemption provider (Phase F.4 — admin-gated).

    Creates the provider row AND the associated provider_redemption_wallet
    account (in PTS) atomically. `tenant_id` is in the body because
    Keycloak admins span tenants (matches the reconciliation router pattern).

    `shared_secret` (Phase F.5) is the HMAC-SHA256 key the provider uses
    to sign callback payloads. NULL = provider does not callback; all
    transitions must come through the admin operator override endpoints.
    """

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    status_check_url: str | None = Field(default=None, max_length=500)
    max_retries: int = Field(default=3, ge=0, le=20)
    retry_interval_secs: int = Field(default=300, ge=1)
    escalate_after_mins: int = Field(default=60, ge=1)
    # Min 32 chars so a low-entropy secret can't slip in; max 1024 is plenty
    # of headroom for any reasonable HMAC key.
    shared_secret: str | None = Field(default=None, min_length=32, max_length=1024)


class ProviderOut(BaseModel):
    """Provider resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    redemption_wallet_account_id: UUID
    status_check_url: str | None
    max_retries: int
    retry_interval_secs: int
    escalate_after_mins: int
    status: str


class InitiateRedemptionRequest(BaseModel):
    """Redemption initiation payload (Phase F.4 — auth-gated).

    `tenant_id` and `user_id` come from the session token via
    `get_current_user`. Body carries only the provider + amount.

    `pin` is optional — only required when a `step_up_policies` row
    for ("redemption", "PTS") sets a threshold below `points_amount`.
    """

    provider_id: UUID
    points_amount: Decimal = Field(gt=Decimal("0"))
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    # Optional derived service to transact under. Omitted -> plain 'redemption'
    # (identical to pre-existing behaviour). Resolved ONCE, up front, and used
    # for every downstream permission / pricing / limits / ledger step (spec §7).
    service_code: str | None = Field(default=None, max_length=50)


class ConfirmRedemptionRequest(BaseModel):
    """Admin payload simulating provider success callback (Pay-PRD-0690).

    Phase F.5 will replace this with HMAC-verified provider callbacks. For
    Phase F.4 the endpoint is admin-gated; tenant scopes the lookup.
    """

    tenant_id: UUID
    external_reference: str | None = Field(default=None, max_length=255)


class FailRedemptionRequest(BaseModel):
    """Admin payload simulating provider failure (Pay-PRD-0700).

    Same auth gate as ConfirmRedemptionRequest. Phase F.5 added the real
    HMAC-verified provider callback (`/callback`); these `/confirm` and
    `/fail` admin endpoints remain as operator overrides.
    """

    tenant_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class ProviderCallbackRequest(BaseModel):
    """HMAC-verified provider callback payload (Phase F.5, Pay-PRD-0690/0700).

    The provider POSTs this body with an `X-Sasai-Signature` header. The
    router verifies the signature against the provider's decrypted
    `shared_secret_encrypted` BEFORE
    Pydantic parses this schema — Pydantic-normalised bytes would invalidate
    the HMAC.
    """

    outcome: Literal["completed", "failed"]
    external_reference: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=500)


class RedemptionOut(BaseModel):
    """Redemption resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    # Resolved display name of the redeeming user, populated on the admin
    # operator-override responses (confirm / fail) so operators see a name
    # rather than a bare id. None on user-facing responses and when the user
    # has no resolvable name — the UI then falls back to a short id.
    user_name: str | None = None
    provider_id: UUID
    transaction_id: UUID
    points_amount: Decimal
    status: str
    external_reference: str | None
    failure_reason: str | None
    completed_at: datetime | None
    created_at: datetime


class ConversionRateCreateRequest(BaseModel):
    """Admin payload for a per-(tenant, currency) points→fiat conversion rate.

    Read as "`points_per_unit` PTS = `value_per_unit` `currency`" — e.g.
    100 PTS = 10.00 ZAR. Rides the config change-request maker-checker
    (config_type `conversion_rate`, Pay-PRD-1210). Exactly one rate per
    (tenant, currency); both sides must be positive.
    """

    tenant_id: UUID
    currency: str = Field(min_length=2, max_length=10)
    points_per_unit: Decimal = Field(gt=Decimal("0"))
    value_per_unit: Decimal = Field(gt=Decimal("0"))


class ConversionRateOut(BaseModel):
    """Conversion-rate resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    currency: str
    points_per_unit: Decimal
    value_per_unit: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class InternalRedemptionRequest(BaseModel):
    """User payload for an internal redemption (Pay-PRD-1200, design 07 §6.3).

    `tenant_id` / `user_id` come from the session token. Body carries the
    points to burn and the destination wallet currency; `pin` is required only
    when a step-up policy for ("redemption", "PTS") sets a threshold below
    `points_amount`.
    """

    points_amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=2, max_length=10)
    pin: str | None = Field(default=None, min_length=4, max_length=12)


class InternalRedemptionOut(BaseModel):
    """Internal-redemption receipt — the cross-referenced points/fiat pair."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    points_transaction_id: UUID
    payout_transaction_id: UUID
    currency: str
    points_amount: Decimal
    fiat_amount: Decimal
    points_per_unit: Decimal
    value_per_unit: Decimal
    created_at: datetime
