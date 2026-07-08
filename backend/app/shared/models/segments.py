"""Segment + UserSegment models — Epic 10 / WAL-79.

Static cohorts of users that admins can target with rules or
multipliers. Membership is explicit (admin assigns each user); dynamic
"users who did X" segments are deferred to Phase 2.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk


class Segment(Base):
    """A named user cohort within a tenant."""

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_segments_name_per_tenant"),
        Index("ix_segments_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class UserSegment(Base):
    """Many-to-many — assigns a user to a segment."""

    __tablename__ = "user_segments"
    __table_args__ = (
        UniqueConstraint("user_id", "segment_id", name="uq_user_segments_pair"),
        Index("ix_user_segments_user", "user_id"),
        Index("ix_user_segments_segment", "segment_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = created_at_col()
