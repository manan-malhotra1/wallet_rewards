"""Pydantic v2 schemas for the reconciliation module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SweepRequest(BaseModel):
    """Request body for `POST /reconciliation/sweep`.

    `threshold_minutes` is how long a redemption must have been PENDING before
    it's considered stale and eligible for retry. Default 5 — short enough for
    test demos, long enough that healthy redemptions aren't disturbed.
    """

    tenant_id: UUID
    threshold_minutes: int = Field(default=5, ge=0, le=60 * 24 * 7)


class PendingItem(BaseModel):
    """One row in the PENDING redemption list (Pay-PRD-0750)."""

    model_config = ConfigDict(from_attributes=True)

    redemption_id: UUID
    transaction_id: UUID
    user_id: UUID
    # Resolved display name of the redeeming user; None when the user has no
    # profile name or identifier, so the UI falls back to a short user id.
    user_name: str | None = None
    provider_id: UUID
    points_amount: Decimal
    retry_count: int
    last_checked_at: datetime | None
    created_at: datetime


class ManualReviewItem(BaseModel):
    """One row in the MANUAL_REVIEW queue."""

    model_config = ConfigDict(from_attributes=True)

    redemption_id: UUID
    transaction_id: UUID
    user_id: UUID
    # Resolved display name of the redeeming user; None when the user has no
    # profile name or identifier, so the UI falls back to a short user id.
    user_name: str | None = None
    provider_id: UUID
    points_amount: Decimal
    retry_count: int
    last_checked_at: datetime | None
    created_at: datetime


class SweepOutcome(BaseModel):
    """Result of a sweep run."""

    scanned_count: int
    bumped_count: int
    escalated_count: int
    audit_entry_count: int


class ResolveRequest(BaseModel):
    """Request body for manual resolve.

    `outcome=COMPLETED` flips the ledger entries PENDING -> COMPLETED (the
    operator vouches the provider actually succeeded).
    `outcome=REVERSED` flips PENDING -> REVERSED, restoring the user's points
    (the operator vouches the provider failed or the redemption is unsafe).
    """

    tenant_id: UUID
    outcome: Literal["COMPLETED", "REVERSED"]
    reason: str = Field(min_length=1, max_length=500)
    external_reference: str | None = Field(default=None, max_length=255)


class AuditEntry(BaseModel):
    """Read-side representation of an audit_log row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    actor_id: str
    actor_type: str
    action: str
    entity_type: str
    entity_id: str
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    ip_address: str | None
    note: str | None
    created_at: datetime
