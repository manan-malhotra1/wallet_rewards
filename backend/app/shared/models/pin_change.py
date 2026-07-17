"""PinChange model — user self-service PIN change (charged service).

A user changes their own PIN. Change-PIN is a CHARGED service subject to
invariant #12 (fail-closed on BOTH pricing AND limit config), but it has NO
principal: when the configured fee is zero there are no ledger legs at all
(`post_transaction` requires >= 2 balanced entries), yet the operation must
still be idempotent and audited. This domain row carries idempotency
independent of any ledger transaction — mirroring `AirtimeRecharge`'s
`(tenant_id, idempotency_key)` unique key — and links to the fee transaction
via a nullable `transaction_id` (set only when a non-zero fee was posted).

Per NFR-0170 no PIN or PIN hash is ever stored on this row — only the charge
breakdown (fee / tax / currency / status) and the idempotency key.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, uuid_pk

# Change-PIN status — a change-PIN either fully applies or it does not persist
# at all (there is no external provisioning step), so the only terminal state
# recorded here is COMPLETED. Kept as a constant + CHECK for forward room.
PIN_CHANGE_STATUS_COMPLETED = "completed"


class PinChange(Base):
    """One user's completed PIN change plus its charge breakdown.

    `transaction_id` is NULL when the resolved fee (and tax) was zero — a
    zero-fee change moves no money, so no ledger transaction exists. When a
    fee/tax was charged it links to that fee-only double-entry transaction.
    Idempotency is at THIS layer (not the ledger): a replay with the same
    `(tenant_id, idempotency_key)` returns the original row without re-charging
    or re-verifying the PIN.
    """

    __tablename__ = "pin_changes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed')",
            name="ck_pin_changes_status",
        ),
        # Idempotency at the change-PIN layer — a duplicate
        # (tenant, idempotency_key) returns the original row (Pay-PRD-0200).
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_pin_changes_idempotency_per_tenant",
        ),
        Index("ix_pin_changes_tenant", "tenant_id"),
        Index("ix_pin_changes_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fee_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, server_default="0")
    tax_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, server_default="0")
    # Set only when a fee was posted; NULL for a zero-fee change (no ledger txn).
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=PIN_CHANGE_STATUS_COMPLETED
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
