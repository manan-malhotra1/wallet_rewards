"""Request schemas for the external partner API (Epic 14).

Deliberately a RESTRICTED shape (Epic 14 S7 / mass-assignment hardening,
finding H1): a partner CANNOT set `user_type`, `parent_user_id`, or an
identifier's `verified` flag — those are privilege/trust-relevant and are
forced server-side in the router. Reusing the admin `CreateUserRequest` /
`IdentifierIn` shapes for an untrusted caller would let a partner pick its own
limit/pricing tier or assert unverified contact details as verified.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ExternalFundRequest(BaseModel):
    """Partner-facing fund payload — credits an existing user's wallet.

    No `tenant_id` (derived from the API key). `extra='forbid'` rejects any
    unexpected field outright (BOPLA hardening, mirrors Epic 17 S7). The target
    is resolved by identifier and is always a user's financial_wallet.
    """

    model_config = ConfigDict(extra="forbid")

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    # Bounded to the ledger's Numeric(20, 6) storage precision — a larger/more
    # precise value can't be stored faithfully anyway (M-01/L-03 defence-in-depth).
    # NOTE: this bounds a single request's magnitude, not cumulative partner
    # funding — a mandatory per-tenant funding ceiling is a separate policy call.
    amount: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=6)
    currency: str = Field(min_length=2, max_length=10)
    reason: str | None = Field(default=None, max_length=500)
    # Optional derived service to transact under (spec §8 — partner keys may
    # name a derived service). Omitted -> plain 'fund', identical to
    # pre-existing behaviour.
    service_code: str | None = Field(default=None, max_length=50)


class MerchantCashinRequest(BaseModel):
    """Partner-facing merchant cash-in payload — merchant funds a consumer.

    A merchant-bound API key credits the resolved consumer's wallet from the
    MERCHANT's own wallet (the merchant is identified by the key, never the
    body). No `tenant_id` / `merchant` field — both come from the key.
    `extra='forbid'` rejects any unexpected field (BOPLA hardening).
    """

    model_config = ConfigDict(extra="forbid")

    # The CONSUMER recipient, resolved by identifier within the key's tenant.
    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    # Bounded to the ledger's Numeric(20, 6) storage precision.
    amount: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=6)
    currency: str = Field(min_length=2, max_length=10)
    reason: str | None = Field(default=None, max_length=500)
    # Optional derived service to transact under (spec §8 — partner keys may
    # name a derived service). Omitted -> plain 'merchant_cashin', identical
    # to pre-existing behaviour.
    service_code: str | None = Field(default=None, max_length=50)


class MerchantCashinResponse(BaseModel):
    """Result of a merchant cash-in — both wallet balances after the move."""

    transaction_id: UUID
    merchant_user_id: UUID
    consumer_user_id: UUID
    amount: Decimal
    currency: str
    merchant_new_balance: Decimal
    consumer_new_balance: Decimal


class ExternalWithdrawRequest(BaseModel):
    """Partner-facing withdraw payload — debits a user's wallet.

    Supply exactly one of `amount` or `withdraw_all`; `withdraw_all=true` (with
    no amount) pulls the full available balance. No `tenant_id` (from the key).
    Only ever targets the user's financial_wallet, never a system wallet.
    """

    model_config = ConfigDict(extra="forbid")

    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    # Bounded to the ledger's Numeric(20, 6) storage precision (M-01/L-03).
    amount: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=20, decimal_places=6)
    withdraw_all: bool = False
    currency: str = Field(min_length=2, max_length=10)
    reason: str | None = Field(default=None, max_length=500)
    # Optional derived service to transact under (spec §8 — partner keys may
    # name a derived service). Omitted -> plain 'withdraw', identical to
    # pre-existing behaviour.
    service_code: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _amount_xor_withdraw_all(self) -> Self:
        """Exactly one of amount / withdraw_all must be provided."""
        if self.withdraw_all and self.amount is not None:
            raise ValueError("Provide either amount or withdraw_all, not both.")
        if not self.withdraw_all and self.amount is None:
            raise ValueError("amount is required unless withdraw_all is true.")
        return self
