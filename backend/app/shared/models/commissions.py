"""CommissionConfig model — Pricing v2 Epic 19 (Story 19.3).

A commission schedule per (tenant, transaction_type, currency, user_type) with
amount bands, structurally a twin of `PricingConfig`. The commission is the
platform-funded, always-additive payout to the acting agent for a service:
`commission = fixed_commission + min(variable_commission_pct * amount,
commission_cap)`, resolved against the acting agent's `user_type`.

Unlike pricing there is no `account_type` dimension — a commission is always a
credit to the agent's financial wallet from the `commission` pool.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class CommissionConfig(Base):
    """Commission schedule per (tenant, txn-type, currency, user_type) + band."""

    __tablename__ = "commission_configs"
    __table_args__ = (
        # NULLS NOT DISTINCT so two NULL-type/NULL-band rows for the same other
        # dims collide (PG 15+). Mirrors uq_pricing_configs_scope.
        UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "currency",
            "user_type",
            "amount_from",
            name="uq_commission_configs_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "fixed_commission >= 0",
            name="ck_commission_configs_fixed_nonneg",
        ),
        CheckConstraint(
            "variable_commission_pct >= 0 AND variable_commission_pct < 1",
            name="ck_commission_configs_variable_pct_range",
        ),
        CheckConstraint(
            "amount_from IS NULL OR amount_to IS NULL OR amount_to > amount_from",
            name="ck_commission_configs_amount_band",
        ),
        CheckConstraint(
            "payout_destination IN ('main_wallet', 'commission_wallet')",
            name="ck_commission_configs_payout_destination",
        ),
        CheckConstraint(
            "parent_fixed_commission >= 0",
            name="ck_commission_configs_parent_fixed_nonneg",
        ),
        CheckConstraint(
            "parent_variable_commission_pct >= 0 AND parent_variable_commission_pct < 1",
            name="ck_commission_configs_parent_variable_pct_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # NULL = default commission for all user types; an exact-type row wins.
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The band [amount_from, amount_to) this row applies to. Both NULL = all.
    amount_from: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    amount_to: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # commission = fixed_commission + min(variable_commission_pct*amount, cap).
    fixed_commission: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    variable_commission_pct: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, server_default="0"
    )
    commission_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # Where the commission lands (spec 2026-08-26, D6). 'main_wallet'
    # reproduces the pre-commission-wallet behaviour exactly, which is why it
    # is the server default: migration 0067 backfills every existing row to it
    # and nothing reprices on deploy (D18).
    payout_destination: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="main_wallet"
    )
    # The earner's PARENT is paid from the SAME row, using the same amount band
    # and precedence (spec D8). The rate is a percentage of the TRANSACTION
    # AMOUNT, not of the child's commission — symmetric with the child terms,
    # which is what lets both legs share one resolver and one band-replace.
    parent_fixed_commission: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    parent_variable_commission_pct: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, server_default="0"
    )
    parent_commission_cap: Mapped[float | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
