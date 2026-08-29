"""Internal-redemption models — PRD Module 11b (Pay-PRD-1200-1290).

`PointsConversionRate` holds the per-(tenant, currency) points→fiat rate and
`InternalRedemption` binds the two ledger transactions each redemption posts
(design doc 07 §6). The external, provider-fulfilled tables that used to live
here (`redemption_providers`, `redemptions`) were dropped in migration 0070:
points are already monetised into real money by the internal path, so a
second provider-fulfilled route was redundant.
"""

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


class PointsConversionRate(Base):
    """Per-(tenant, currency) points→fiat conversion rate (Pay-PRD-1210).

    Read as "`points_per_unit` PTS = `value_per_unit` `currency`" — e.g.
    100 PTS = 10.00 ZAR. Exactly one row per (tenant, currency); changes ride
    the config change-request maker-checker like pricing/limits. The internal
    redemption gate is FAIL-CLOSED on this table (Pay-PRD-1220): no ACTIVE row
    for the requested currency → 422 `conversion_rate_missing`, never a
    default rate.
    """

    __tablename__ = "points_conversion_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "currency", name="uq_points_conversion_rates_scope"),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_points_conversion_rates_status",
        ),
        CheckConstraint("points_per_unit > 0", name="ck_points_conversion_rates_points"),
        CheckConstraint("value_per_unit > 0", name="ck_points_conversion_rates_value"),
        CheckConstraint(
            "max_points_per_txn IS NULL OR max_points_per_txn > 0",
            name="ck_points_conversion_rates_txn_cap",
        ),
        CheckConstraint(
            "max_balance_pct_per_txn IS NULL OR "
            "(max_balance_pct_per_txn > 0 AND max_balance_pct_per_txn <= 100)",
            name="ck_points_conversion_rates_pct_cap",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    points_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    value_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Per-transaction anti-drain caps (Pay-PRD-1295). NULL = uncapped on that
    # axis: an absolute points ceiling, and/or a max percentage of the user's
    # CURRENT points balance a single redemption may burn.
    max_points_per_txn: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_balance_pct_per_txn: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class InternalRedemption(Base):
    """One completed internal redemption — the points↔fiat pair binding row.

    Cross-references the two balanced ledger transactions (Pay-PRD-1250/1260):
    the PTS burn (`points_transaction_id`) and the fiat payout
    (`payout_transaction_id`). The conversion rate is SNAPSHOTTED here so later
    rate changes never reinterpret history. Redemptions settle synchronously —
    there is no PENDING state to chase.
    """

    __tablename__ = "internal_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_internal_redemptions_idempotency"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    points_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    payout_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    points_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    fiat_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Rate snapshot at redemption time (points_per_unit PTS = value_per_unit currency).
    points_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    value_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
