"""Pydantic v2 schemas for the catalog module."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PointsSummary(BaseModel):
    """Snapshot of a user's points-account state (Pay-PRD-0970)."""

    currency: str
    available: Decimal
    reserved: Decimal
    lifetime_earned: Decimal
    lifetime_redeemed: Decimal


class CatalogSummaryResponse(BaseModel):
    """Top-level user catalog response."""

    user_id: UUID
    tenant_id: UUID
    points: PointsSummary | None  # None when user has no points account


class RedemptionHistoryItem(BaseModel):
    """One row in the user's redemption history (Pay-PRD-1030)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    points_amount: Decimal
    status: str
    external_reference: str | None
    failure_reason: str | None
    completed_at: datetime | None
    created_at: datetime


class PointsHistoryItem(BaseModel):
    """One row in the user's points ledger history (Pay-PRD-0980).

    A direct view of `ledger_entries` on the user's points_account, enriched
    with the parent transaction's type and (for reward credits) the rule
    name that caused the entry.
    """

    ledger_entry_id: UUID
    direction: str           # "CREDIT" or "DEBIT"
    amount: Decimal
    status: str              # PENDING, COMPLETED, REVERSED
    transaction_type: str    # reward_issuance, redemption, etc.
    rule_name: str | None    # populated for reward_issuance entries
    triggering_event_id: str | None
    occurred_at: datetime
