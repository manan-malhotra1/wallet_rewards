"""TaxConfig model — Pricing v2 Epic 19 (Story 19.4).

Jurisdiction-wide tax rates per (tenant, currency): a rate on fees and a rate
on commissions, each with its own inclusive/exclusive flag (axes 2 and 3 of the
charge matrix). Kept in a separate table rather than co-located on every
pricing/commission row because VAT is jurisdiction-wide — denormalising it would
force the same rate onto every band.
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


class TaxConfig(Base):
    """Tax rates + inclusive flags per (tenant, currency)."""

    __tablename__ = "tax_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "currency",
            name="uq_tax_configs_scope",
        ),
        CheckConstraint(
            "fee_tax_pct >= 0 AND fee_tax_pct < 1",
            name="ck_tax_configs_fee_tax_pct_range",
        ),
        CheckConstraint(
            "commission_tax_pct >= 0 AND commission_tax_pct < 1",
            name="ck_tax_configs_commission_tax_pct_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    # Rate applied to the fee (axis 2) and to the commission (axis 3).
    fee_tax_pct: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False, server_default="0")
    commission_tax_pct: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, server_default="0"
    )
    # Axis 2 — is the fee's tax already inside the fee (inclusive) or added on
    # top (exclusive, default). Axis 3 — same for the commission's tax.
    fee_tax_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    commission_tax_inclusive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
