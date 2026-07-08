"""Instrument catalog model (Phase 3 of the Tenant Management refactor).

Each row is one value unit a tenant uses — a currency or a points unit.
`code` (≤10 chars) becomes the persistent identifier referenced by every
`currency` column across the platform (accounts, ledger_entries,
transactions, limit_configs, pricing_configs, step_up_policies,
reward_budgets, airtime_recharges, tenants.base_currency).

`account_type` is the kind of account auto-provisioned for users when
they hold balance in this instrument — Phase-1 baseline maps ZAR →
financial_wallet and PTS → points_account; tenants pick the right type
when creating new instruments.

Soft-deletion mirrors the services catalog: the partial-UNIQUE index
on (tenant_id, code) WHERE deleted_at IS NULL lets a tenant re-create
the same code after deleting it. Existing ledger rows referencing the
deleted code remain valid (no FK enforcement).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

INSTRUMENT_STATUS_ACTIVE = "active"
INSTRUMENT_STATUS_DISABLED = "disabled"


class Instrument(Base):
    """A configurable value unit on a tenant."""

    __tablename__ = "instruments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_instruments_status",
        ),
        Index("ix_instruments_tenant", "tenant_id"),
        # Partial-UNIQUE: see services.py for the same pattern.
        Index(
            "uq_instruments_tenant_code_alive",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=INSTRUMENT_STATUS_ACTIVE
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
