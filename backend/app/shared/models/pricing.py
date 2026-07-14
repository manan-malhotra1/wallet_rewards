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
    Boolean,
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
        # NULLS NOT DISTINCT so two NULL-type rows for the same other dims
        # collide (PG 15+). Epic 16 — type-aware pricing. Pricing v2 (Epic 19)
        # adds `amount_from` to the scope so several amount bands can coexist
        # for one (tenant, txn-type, account, currency, user_type) slot.
        UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "account_type",
            "currency",
            "user_type",
            "amount_from",
            name="uq_pricing_configs_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "fixed_fee >= 0",
            name="ck_pricing_configs_fixed_fee_nonneg",
        ),
        CheckConstraint(
            "variable_fee_pct >= 0 AND variable_fee_pct < 1",
            name="ck_pricing_configs_variable_fee_pct_range",
        ),
        CheckConstraint(
            "user_type IN ('consumer', 'agent', 'super_agent', 'merchant', 'head_merchant')",
            name="ck_pricing_configs_user_type",
        ),
        # A band is a half-open interval [amount_from, amount_to); the upper
        # bound must exceed the lower when both are set.
        CheckConstraint(
            "amount_from IS NULL OR amount_to IS NULL OR amount_to > amount_from",
            name="ck_pricing_configs_amount_band",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # Type-aware scope (Epic 16): NULL = default fee for all user types; an
    # exact-type row wins over the NULL default in quote_fee resolution.
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Amount-slab scope (Epic 19): the band `[amount_from, amount_to)` this row
    # applies to. Both NULL = applies to all amounts (back-compat with the
    # single-row configs that predate slabs). A specific band wins over the
    # NULL-band default in resolution (ORDER BY amount_from NULLS LAST).
    amount_from: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    amount_to: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # `fixed_fee` is always charged regardless of amount. `variable_fee_pct`
    # is multiplied by the transaction amount (0.025 = 2.5%). `fee_cap`
    # caps the variable component — total fee = fixed + min(pct*amount, fee_cap).
    fixed_fee: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, server_default="0")
    variable_fee_pct: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, server_default="0"
    )
    fee_cap: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # Axis 1 of the inclusive/exclusive matrix (Epic 19). False (default) =
    # exclusive: the payer pays `amount + fee` and the beneficiary receives the
    # full `amount`. True = inclusive: the payer pays `amount` and the
    # beneficiary receives `amount - fee`. The charge assembler owns this.
    fee_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
