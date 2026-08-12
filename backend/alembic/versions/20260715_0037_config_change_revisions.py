"""create config_change_revisions — per-revision payload snapshots.

Additive to the maker-checker flow (Pricing v2 Epic 22): the request row keeps
only the latest payload, so revising overwrites the prior version. This table
appends one immutable snapshot per revision so maker + checker can read every
version of an edited config. Existing rows only have their latest payload, so
we backfill ONE snapshot each at the request's current revision.

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the snapshot table + unique index, then backfill existing requests."""
    op.create_table(
        "config_change_revisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["config_change_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id", "revision", name="uq_config_change_revisions_request_revision"
        ),
    )
    op.create_index(
        "ix_config_change_revisions_request",
        "config_change_revisions",
        ["request_id", "revision"],
    )

    # Backfill: one snapshot per existing request at its CURRENT revision with
    # its CURRENT payload — the only version history we can recover.
    op.execute(
        """
        INSERT INTO config_change_revisions
            (id, tenant_id, request_id, revision, payload, created_at)
        SELECT gen_random_uuid(), tenant_id, id, revision, payload, now()
        FROM config_change_requests
        """
    )


def downgrade() -> None:
    """Drop the snapshot table (and its index)."""
    op.drop_index("ix_config_change_revisions_request", table_name="config_change_revisions")
    op.drop_table("config_change_revisions")
