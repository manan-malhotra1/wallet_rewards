"""Pydantic v2 schemas for the money-operation maker-checker module (Epic 18).

Each money operation carries an operation-specific `payload` matching the
arguments of the treasury service function it eventually applies to. The
per-operation payload schemas below are the single source of truth for that
shape — `propose`/`revise` validate against them (fail fast, 422) and `apply`
re-parses the stored JSON back through them before dispatching to treasury.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.treasury.schemas import TreasuryIdentifierType
from app.shared.models import (
    MONEY_OP_ADJUST_SYSTEM,
    MONEY_OP_CREATE_BANK_MIRROR,
    MONEY_OP_FUND_USER,
    MONEY_OP_WITHDRAW_USER,
)

# -----------------------------------------------------------------------------
# Per-operation payloads (mirror the treasury service fn signatures)
# -----------------------------------------------------------------------------


class FundUserPayload(BaseModel):
    """Payload for `fund_user` — top up a user's wallet by identifier."""

    identifier_type: TreasuryIdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=2, max_length=10)
    reason: str | None = Field(default=None, max_length=500)


class WithdrawUserPayload(BaseModel):
    """Payload for `withdraw_from_user` — pull funds from a user's wallet.

    Supply exactly one of `amount` or `withdraw_all`, mirroring the treasury
    request. `bank_mirror_account_id` is the counter-leg the operator picks.
    """

    identifier_type: TreasuryIdentifierType
    identifier_value: str = Field(min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    withdraw_all: bool = False
    currency: str = Field(min_length=2, max_length=10)
    bank_mirror_account_id: UUID
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _amount_xor_withdraw_all(self) -> Self:
        """Exactly one of amount / withdraw_all must be provided."""
        if self.withdraw_all and self.amount is not None:
            raise ValueError("Provide either amount or withdraw_all, not both.")
        if not self.withdraw_all and self.amount is None:
            raise ValueError("amount is required unless withdraw_all is true.")
        return self


class AdjustSystemWalletPayload(BaseModel):
    """Payload for `adjust_system_wallet` — signed fund/withdraw of a system wallet."""

    account_id: UUID
    amount: Decimal  # signed, non-zero
    bank_mirror_account_id: UUID
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _amount_non_zero(self) -> Self:
        """A zero adjustment is a no-op and rejected early."""
        if self.amount == 0:
            raise ValueError("Amount must be non-zero.")
        return self


class CreateBankMirrorPayload(BaseModel):
    """Payload for `create_bank_mirror` — a new named operator_adjustment account."""

    currency: str = Field(min_length=2, max_length=10)
    name: str = Field(min_length=1, max_length=100)


# operation -> its payload schema. The single lookup used by propose/revise
# (validate) and apply (re-parse the stored JSON).
PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    MONEY_OP_FUND_USER: FundUserPayload,
    MONEY_OP_WITHDRAW_USER: WithdrawUserPayload,
    MONEY_OP_ADJUST_SYSTEM: AdjustSystemWalletPayload,
    MONEY_OP_CREATE_BANK_MIRROR: CreateBankMirrorPayload,
}


# -----------------------------------------------------------------------------
# API request / response schemas
# -----------------------------------------------------------------------------


class MoneyOperationProposeRequest(BaseModel):
    """A maker's proposal of a money operation.

    `payload` is validated against the schema for `operation` at propose time;
    an invalid payload is a 422 before anything is written.
    """

    operation: str
    payload: dict[str, object]


class MoneyOperationReviseRequest(BaseModel):
    """A maker's in-place edit of a CHANGES_REQUESTED request's payload."""

    payload: dict[str, object]


class MoneyOperationCommentRequest(BaseModel):
    """A checker's request-changes with the mandatory comment."""

    comment: str = Field(min_length=1, max_length=2000)


class MoneyReviewOut(BaseModel):
    """One entry in a money operation's append-only review thread."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_admin_id: str
    # Resolved display name for actor_admin_id (None if not yet recorded).
    actor_admin_name: str | None = None
    actor_role: str
    action: str
    comment: str | None
    created_at: datetime


class MoneyOperationOut(BaseModel):
    """A money-operation request, with its review thread + N-eyes progress.

    `approvals_count` is the number of DISTINCT checker approvals recorded in
    the CURRENT approval round (since the latest resubmit) — it reaches
    `required_approvals` at the moment the operation applies.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    operation: str
    payload: dict[str, object]
    status: str
    maker_admin_id: str
    # Resolved display name (None if the admin hasn't been recorded yet).
    maker_admin_name: str | None = None
    required_approvals: int
    approvals_count: int = 0
    applied_transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime
    reviews: list[MoneyReviewOut] = Field(default_factory=list)
    # Best-effort resolved display names so the UI shows people/wallets, not
    # raw identifiers/UUIDs. None when unresolvable (UI falls back to payload).
    subject_name: str | None = None  # funded/withdrawn user (fund_user/withdraw_user)
    account_name: str | None = None  # target system account (adjust_system_wallet)
    bank_mirror_name: str | None = None  # bank-mirror leg (adjust_system_wallet/withdraw_user)
