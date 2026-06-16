"""LimitConfig model — Phase G.2 (PRD Module 5).

Per (tenant, transaction_type, account_type, currency) min/max plus
daily count + value caps. The limits service consults this before any
ledger write in the payment orchestration sequence (Pay-PRD-0260 step 2).

When no row exists for a tuple, the limits check is a no-op (graceful
pass-through). Operators MUST opt-in by inserting configs.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class LimitConfig(Base):
    """A per-(tenant, txn-type, account-type, currency) limit config."""

    __tablename__ = "limit_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "account_type",
            "currency",
            name="uq_limit_configs_scope",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)

    # All four are nullable — operators can configure just min/max, just
    # the daily caps, or any combination. NULL means "no limit on this axis".
    min_amount: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_amount: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    daily_count_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_value_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
