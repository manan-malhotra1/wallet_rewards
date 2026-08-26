"""Pydantic v2 schemas for the commission-batches module (spec 2026-08-26 §8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

BatchType = Literal["disbursement", "withdrawal"]


class BatchRowOut(BaseModel):
    """One row as the checker sees it.

    `delta` is the point of the checker screen: it makes "accrued R1,620, paying
    R1,500" visible at a glance, with the maker's note supplying the why.
    `snapshot_at` is shown alongside because the balance can drift between
    upload and approval — apply re-checks it under the row lock (spec §8.4).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    row_number: int
    msisdn: str
    currency: str
    amount: Decimal
    note: str | None
    balance_snapshot: Decimal | None
    snapshot_at: datetime | None
    delta: Decimal | None
    status: str
    failure_reason: str | None
    transaction_id: UUID | None


class BatchOut(BaseModel):
    """A batch header, with rows when the detail endpoint returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    # Plain str on the way OUT (the DB CHECK is the guard, exactly as for
    # `status`); the Literal is enforced on the way IN, at the router.
    batch_type: str
    status: str
    file_name: str
    row_count_total: int
    row_count_valid: int
    amount_total: Decimal
    destination_account_id: UUID | None
    created_by_admin_id: str
    required_approvals: int
    approvals_received: int
    created_at: datetime
    rows: list[BatchRowOut] = []


class BatchRejectRequest(BaseModel):
    """Whole-batch rejection body. The comment is mandatory (D16)."""

    model_config = ConfigDict(extra="forbid")

    comment: str
