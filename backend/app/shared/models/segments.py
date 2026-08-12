"""Segment, SegmentGroup + UserSegment models — Epic 10 / WAL-79 + segmentation Phase 1.

Segments live inside groups (one lens per group, e.g. Customer Loyalty);
a segment's name is unique within its group, not tenant-wide, since two
different groups may legitimately reuse a tier name (e.g. "Gold" under
both "Customer Loyalty" and "Merchant Tiers"). A segment with non-null
`criteria` is dynamic: the batch evaluator
(app/modules/segments/evaluator.py) computes its membership; within a
group membership is exclusive and the highest `priority` match wins.
`criteria IS NULL` segments keep today's manual, admin-assigned behaviour.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# UserSegment.source discriminates admin-assigned membership from
# evaluator-computed membership (see UserSegment.source docstring below).
USER_SEGMENT_SOURCE_MANUAL = "manual"
USER_SEGMENT_SOURCE_CRITERIA = "criteria"


class SegmentGroup(Base):
    """A segmentation lens (e.g. Customer Loyalty) holding exclusive tiers."""

    __tablename__ = "segment_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_segment_groups_name_per_tenant"),
        Index("ix_segment_groups_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Seeded groups (incl. the "General" backfill group): rename/delete protected.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Segment(Base):
    """A named user cohort within a tenant, belonging to exactly one group.

    The segment name is unique within its group (`uq_segments_name_per_group`
    on tenant_id, group_id, name) — not tenant-wide — since a group is the
    exclusive-tier lens and two different groups may reuse a tier name.
    """

    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "group_id", "name", name="uq_segments_name_per_group"),
        Index("ix_segments_tenant", "tenant_id"),
        Index("ix_segments_group", "group_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Every segment belongs to exactly one group (backfilled to "General").
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segment_groups.id"), nullable=False
    )
    # NULL = static/manual segment (legacy behaviour). Non-null = dynamic;
    # shape is validated by app.modules.segments.criteria.SegmentCriteria.
    criteria: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Within an exclusive group the highest matching priority wins (Gold=3 > Bronze=1).
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class UserSegment(Base):
    """Many-to-many — assigns a user to a segment."""

    __tablename__ = "user_segments"
    __table_args__ = (
        UniqueConstraint("user_id", "segment_id", name="uq_user_segments_pair"),
        Index("ix_user_segments_user", "user_id"),
        Index("ix_user_segments_segment", "segment_id"),
        CheckConstraint("source IN ('manual', 'criteria')", name="ck_user_segments_source"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id"), nullable=False
    )
    # 'manual' = admin-assigned (never touched by the evaluator); 'criteria' = computed.
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="manual")
    assigned_at: Mapped[datetime] = created_at_col()
