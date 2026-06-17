"""StepUpPolicy model — per-tenant PIN step-up thresholds.

A user-initiated transaction with `amount > threshold_amount` requires
the user to re-enter their PIN before the ledger is touched. Absence
of a matching row = no step-up ever (current behaviour preserved).

Separate from `limit_configs` because the semantics differ: limits
REJECT past the cap; step-up ESCALATES past the threshold. The two
can coexist on the same (txn_type, currency) — limits apply first.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class StepUpPolicy(Base):
    """A per-(tenant, txn-type, currency) PIN step-up threshold.

    At most one row per scope (UNIQUE on the natural key). `threshold=0`
    means "always require PIN"; absence of a row means "never".
    """

    __tablename__ = "step_up_policies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "currency",
            name="uq_step_up_policies_scope",
        ),
        CheckConstraint(
            "threshold_amount >= 0", name="ck_step_up_policies_threshold_nonneg"
        ),
        Index("ix_step_up_policies_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    threshold_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
