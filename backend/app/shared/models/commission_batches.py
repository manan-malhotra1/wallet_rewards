"""Bulk commission disbursement and withdrawal — spec 2026-08-26 §4.5-4.6.

Three tables mirroring `money_operations.py` conventions: a header carrying the
approval state, an append-only review thread, and — unlike money_operations — a
ROWS table. That rows table is the reason this is a separate module rather than
two new money-operation types: a 5,000-row file needs per-row status, which the
single-payload JSONB design cannot hold.

REJECTED is terminal (spec D16). A checker rejects the whole batch and the maker
uploads a corrected file as a NEW batch; there is deliberately no revise-in-place
loop, so no round counter is needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

BATCH_TYPE_DISBURSEMENT = "disbursement"
BATCH_TYPE_WITHDRAWAL = "withdrawal"
BATCH_TYPES = (BATCH_TYPE_DISBURSEMENT, BATCH_TYPE_WITHDRAWAL)

# Approval-policy operation codes for the two batch kinds, so a tenant can
# require six-eyes on a bulk run while keeping four-eyes on a single treasury op.
BATCH_OPERATION = {
    BATCH_TYPE_DISBURSEMENT: "commission_disbursement",
    BATCH_TYPE_WITHDRAWAL: "commission_withdrawal",
}

BATCH_STATUS_PENDING = "PENDING"
BATCH_STATUS_APPLIED = "APPLIED"
BATCH_STATUS_APPLIED_PARTIAL = "APPLIED_PARTIAL"
BATCH_STATUS_REJECTED = "REJECTED"
BATCH_STATUS_WITHDRAWN = "WITHDRAWN"
BATCH_STATUSES = (
    BATCH_STATUS_PENDING,
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_STATUS_REJECTED,
    BATCH_STATUS_WITHDRAWN,
)
# No further transitions. REJECTED is here because the maker re-uploads a new
# batch rather than revising this one (D16).
BATCH_TERMINAL_STATUSES = (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_APPLIED_PARTIAL,
    BATCH_STATUS_REJECTED,
    BATCH_STATUS_WITHDRAWN,
)

ROW_STATUS_VALID = "valid"
ROW_STATUS_REJECTED = "rejected"
ROW_STATUS_POSTED = "posted"
ROW_STATUS_FAILED = "failed"
ROW_STATUSES = (
    ROW_STATUS_VALID,
    ROW_STATUS_REJECTED,
    ROW_STATUS_POSTED,
    ROW_STATUS_FAILED,
)

REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"


class CommissionBatch(Base):
    """One uploaded disbursement or withdrawal file, pending N-eyes approval."""

    __tablename__ = "commission_batches"
    __table_args__ = (
        CheckConstraint(
            "batch_type IN ('disbursement', 'withdrawal')",
            name="ck_commission_batches_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPLIED', 'APPLIED_PARTIAL', "
            "'REJECTED', 'WITHDRAWN')",
            name="ck_commission_batches_status",
        ),
        CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_commission_batches_required_approvals",
        ),
        Index("ix_commission_batches_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    batch_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count_total: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count_valid: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_total: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Withdrawal only — the named operator_adjustment bank mirror the money
    # lands in. NULL for a disbursement, whose destination is derived per row
    # (the earner's own main wallet).
    destination_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    created_by_admin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Snapshotted at creation so a policy change mid-review cannot move the
    # goalposts on a live batch.
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class CommissionBatchRow(Base):
    """One line of the uploaded file, with its validation and posting state."""

    __tablename__ = "commission_batch_rows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('valid', 'rejected', 'posted', 'failed')",
            name="ck_commission_batch_rows_status",
        ),
        UniqueConstraint(
            "batch_id", "row_number", name="uq_commission_batch_rows_number"
        ),
        Index("ix_commission_batch_rows_batch_status", "batch_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("commission_batches.id"),
        nullable=False,
        index=True,
    )
    # 1-based, EXCLUDING the header — matches what the maker sees in their
    # spreadsheet, so a rejects file is directly actionable.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    msisdn: Mapped[str] = mapped_column(String(30), nullable=False)
    # MANDATORY: a user may hold several commission wallets, so the file must
    # say which one this row moves (spec §4.6).
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Maker-supplied justification for any delta between the wallet balance and
    # the amount moved. The SYSTEM never writes here.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    # Balance at pass-1 validation, with its timestamp — shown to the checker so
    # the delta is visible, and so the STALENESS of that delta is visible too.
    balance_snapshot: Mapped[float | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()


class CommissionBatchReview(Base):
    """Append-only review thread — one row per maker/checker action.

    No `updated_at`: reviews are immutable, matching MoneyOperationReview. The
    UNIQUE (batch_id, admin_id) is what stops one checker supplying two of the
    required approvals; quorum is DERIVED by counting distinct approvers here,
    never stored as a counter that could disagree with the thread.
    """

    __tablename__ = "commission_batch_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_commission_batch_reviews_decision",
        ),
        UniqueConstraint(
            "batch_id", "admin_id", name="uq_commission_batch_reviews_approver"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("commission_batches.id"),
        nullable=False,
        index=True,
    )
    admin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
