"""segment_groups table + dynamic-segment columns + user_segments.source

Adds `segment_groups` (a segmentation lens, e.g. Customer Loyalty) and
attaches every `segments` row to one via a new NOT NULL `group_id`.
Also adds the criteria-engine columns (`criteria`, `priority`, `is_system`,
`last_evaluated_at`) to `segments`, and `source` to `user_segments` so the
Phase-1 batch evaluator (Task 4) can distinguish computed membership from
today's admin-assigned membership. `user_segments.source` is CHECK-guarded
to 'manual' | 'criteria'. Segment-name uniqueness is rescoped from the
tenant to the group (`uq_segments_name_per_group` on
`tenant_id, group_id, name`), since a group is now the exclusive-tier lens
and two different groups may legitimately reuse a tier name.

Backfills a per-tenant system group "General" and attaches every existing
segment to it so `segments.group_id` can be made NOT NULL in the same
migration.

Revision ID: 0053
Revises: 0052
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create segment_groups, add dynamic-segment columns, backfill + add source."""
    op.create_table(
        "segment_groups",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_segment_groups_name_per_tenant"),
    )
    op.create_index("ix_segment_groups_tenant", "segment_groups", ["tenant_id"])

    op.add_column(
        "segments",
        sa.Column(
            "group_id", UUID(as_uuid=True), sa.ForeignKey("segment_groups.id"), nullable=True
        ),
    )
    op.add_column("segments", sa.Column("criteria", JSONB(), nullable=True))
    op.add_column(
        "segments",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "segments",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "segments",
        sa.Column("last_evaluated_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Backfill: one "General" system group per tenant that already has segments,
    # then point every pre-existing segment at its tenant's group. Data backfill
    # via sa.text is acceptable in migrations (the "no raw SQL" rule is for app code).
    op.execute(
        sa.text(
            "INSERT INTO segment_groups (id, tenant_id, name, description, is_system) "
            "SELECT gen_random_uuid(), t.tenant_id, 'General', "
            "'Auto-created for pre-existing segments.', true "
            "FROM (SELECT DISTINCT tenant_id FROM segments) t"
        )
    )
    op.execute(
        sa.text(
            "UPDATE segments s SET group_id = g.id FROM segment_groups g "
            "WHERE g.tenant_id = s.tenant_id AND g.name = 'General'"
        )
    )
    op.alter_column(
        "segments",
        "group_id",
        existing_type=UUID(as_uuid=True),
        existing_nullable=True,
        nullable=False,
    )
    op.create_index("ix_segments_group", "segments", ["group_id"])

    # Names are scoped to the group now (a group is the exclusive-tier lens),
    # not the whole tenant — two different groups may reuse a tier name.
    op.drop_constraint("uq_segments_name_per_tenant", "segments", type_="unique")
    op.create_unique_constraint(
        "uq_segments_name_per_group", "segments", ["tenant_id", "group_id", "name"]
    )

    op.add_column(
        "user_segments",
        sa.Column("source", sa.String(10), nullable=False, server_default=sa.text("'manual'")),
    )
    op.create_check_constraint(
        "ck_user_segments_source",
        "user_segments",
        "source IN ('manual', 'criteria')",
    )


def downgrade() -> None:
    """Drop source (+ its CHECK), the dynamic-segment columns, and segment_groups.

    Restoring uq_segments_name_per_tenant fails if any tenant reused a segment
    name across groups after the upgrade; dedupe those names before rolling back.
    """
    op.drop_constraint("ck_user_segments_source", "user_segments", type_="check")
    op.drop_column("user_segments", "source")

    op.drop_constraint("uq_segments_name_per_group", "segments", type_="unique")
    op.create_unique_constraint("uq_segments_name_per_tenant", "segments", ["tenant_id", "name"])

    op.drop_index("ix_segments_group", table_name="segments")
    op.drop_column("segments", "last_evaluated_at")
    op.drop_column("segments", "is_system")
    op.drop_column("segments", "priority")
    op.drop_column("segments", "criteria")
    op.drop_column("segments", "group_id")
    op.drop_index("ix_segment_groups_tenant", table_name="segment_groups")
    op.drop_table("segment_groups")
