"""BonusMultiplier model — Epic 10 / WAL-78.

A bonus multiplier amplifies a rule's `reward_value` at issuance time.
Scope: per-rule, per-segment, both (intersection), or global within
the tenant.

The "validity window" is the half-open interval `[valid_from, valid_until)`
when both are set; NULL on either end means "open-ended in that direction".
Multiplier resolution at issuance time picks the SINGLE highest-multiplier
row that matches the (rule, user, timestamp) tuple — overlapping
multipliers don't stack, the bigger one wins.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, uuid_pk


class BonusMultiplier(Base):
    """A multiplier applied to reward_value when the scope matches."""

    __tablename__ = "bonus_multipliers"
    __table_args__ = (
        CheckConstraint("multiplier > 0", name="ck_bonus_multipliers_positive"),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until",
            name="ck_bonus_multipliers_window",
        ),
        Index("ix_bonus_multipliers_tenant", "tenant_id"),
        Index("ix_bonus_multipliers_rule", "rule_id"),
        Index("ix_bonus_multipliers_segment", "segment_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # NULL = applies to any rule in the tenant.
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id"), nullable=True
    )
    # NULL = applies to any user in the tenant.
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id"), nullable=True
    )
    multiplier: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
