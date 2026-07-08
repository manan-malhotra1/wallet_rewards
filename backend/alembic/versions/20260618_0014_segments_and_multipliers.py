"""create segments + user_segments + bonus_multipliers

Three tables for Epic 10's last two stories:

* `segments` — admin-defined static cohorts (one row per cohort per tenant).
* `user_segments` — membership; users may belong to multiple segments.
* `bonus_multipliers` — multipliers applied at reward issuance; scoped
  by rule, by segment, or globally per tenant. Active when "now" falls
  in `[valid_from, valid_until]` (both nullable for open-ended).

Also adds a FK from `rules.segment_id` to the new `segments` table —
the column was nullable+orphaned before; it's still nullable but now
referentially valid.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the three tables + the FK on rules.segment_id."""
    op.create_table(
        "segments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_segments_name_per_tenant"),
    )
    op.create_index("ix_segments_tenant", "segments", ["tenant_id"])

    op.create_table(
        "user_segments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("segments.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "segment_id", name="uq_user_segments_pair"),
    )
    op.create_index("ix_user_segments_user", "user_segments", ["user_id"])
    op.create_index("ix_user_segments_segment", "user_segments", ["segment_id"])

    op.create_table(
        "bonus_multipliers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        # NULL → applies to any rule in the tenant (e.g. "Black Friday 2x").
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rules.id"),
            nullable=True,
        ),
        # NULL → applies to any user in the tenant.
        sa.Column(
            "segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("segments.id"),
            nullable=True,
        ),
        sa.Column("multiplier", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "valid_from",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "valid_until",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("multiplier > 0", name="ck_bonus_multipliers_positive"),
        # Either valid_from < valid_until (when both set) or one/both NULL.
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until",
            name="ck_bonus_multipliers_window",
        ),
    )
    op.create_index("ix_bonus_multipliers_tenant", "bonus_multipliers", ["tenant_id"])
    op.create_index("ix_bonus_multipliers_rule", "bonus_multipliers", ["rule_id"])
    op.create_index("ix_bonus_multipliers_segment", "bonus_multipliers", ["segment_id"])

    # Add the FK on rules.segment_id (column already existed, unconstrained).
    op.create_foreign_key(
        "rules_segment_id_fkey",
        "rules",
        "segments",
        ["segment_id"],
        ["id"],
    )


def downgrade() -> None:
    """Drop FK + tables in reverse order."""
    op.drop_constraint("rules_segment_id_fkey", "rules", type_="foreignkey")
    op.drop_index("ix_bonus_multipliers_segment", table_name="bonus_multipliers")
    op.drop_index("ix_bonus_multipliers_rule", table_name="bonus_multipliers")
    op.drop_index("ix_bonus_multipliers_tenant", table_name="bonus_multipliers")
    op.drop_table("bonus_multipliers")
    op.drop_index("ix_user_segments_segment", table_name="user_segments")
    op.drop_index("ix_user_segments_user", table_name="user_segments")
    op.drop_table("user_segments")
    op.drop_index("ix_segments_tenant", table_name="segments")
    op.drop_table("segments")
