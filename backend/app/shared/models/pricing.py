"""PricingConfig model — Phase G.3 (PRD Module 6).

Per (tenant, transaction_type, account_type, currency) fee = fixed +
percentage. The pricing service computes the fee BEFORE the ledger write
(step 3 of Pay-PRD-0260). The fee surfaces in the response and is
written as an additional ledger leg (user wallet DEBIT → system fee
account CREDIT).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class PricingConfig(Base):
    """Fee schedule per (tenant, txn-type, account-type, currency)."""

    __tablename__ = "pricing_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "account_type",
            "currency",
            name="uq_pricing_configs_scope",
        ),
        CheckConstraint(
            "fixed_fee >= 0",
            name="ck_pricing_configs_fixed_fee_nonneg",
        ),
        CheckConstraint(
            "variable_fee_pct >= 0 AND variable_fee_pct < 1",
            name="ck_pricing_configs_variable_fee_pct_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)

    # `fixed_fee` is always charged regardless of amount. `variable_fee_pct`
    # is multiplied by the transaction amount (0.025 = 2.5%). `fee_cap`
    # caps the variable component — total fee = fixed + min(pct*amount, fee_cap).
    fixed_fee: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    variable_fee_pct: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, server_default="0"
    )
    fee_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
