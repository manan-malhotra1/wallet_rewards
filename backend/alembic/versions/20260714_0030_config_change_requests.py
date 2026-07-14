"""create config_change_requests + config_change_reviews (Pricing v2 Epic 22)

Story 22.2 — the maker-checker substrate. `config_change_requests` holds one
proposed create/delete per row (editable payload across revisions);
`config_change_reviews` is the append-only comment/action thread. No config is
written to a real config table until a request reaches APPLIED.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the request + review tables."""
    op.create_table(
        "config_change_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("config_type", sa.String(length=20), nullable=False),
        sa.Column("operation", sa.String(length=10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("target_config_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("maker_admin_id", sa.String(length=255), nullable=False),
        sa.Column("checker_admin_id", sa.String(length=255), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "config_type IN ('pricing', 'limit', 'wallet_limit', 'commission', 'tax')",
            name="ck_config_change_requests_config_type",
        ),
        sa.CheckConstraint(
            "operation IN ('create', 'delete')",
            name="ck_config_change_requests_operation",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CHANGES_REQUESTED', 'APPLIED', 'WITHDRAWN')",
            name="ck_config_change_requests_status",
        ),
    )
    op.create_index(
        "ix_config_change_requests_tenant_status",
        "config_change_requests",
        ["tenant_id", "status"],
    )

    op.create_table(
        "config_change_reviews",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("actor_admin_id", sa.String(length=255), nullable=False),
        sa.Column("actor_role", sa.String(length=10), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["config_change_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "actor_role IN ('maker', 'checker')",
            name="ck_config_change_reviews_actor_role",
        ),
        sa.CheckConstraint(
            "action IN ('submitted', 'changes_requested', 'revised', "
            "'resubmitted', 'approved', 'withdrawn')",
            name="ck_config_change_reviews_action",
        ),
    )
    op.create_index(
        "ix_config_change_reviews_request",
        "config_change_reviews",
        ["request_id", "created_at"],
    )


def downgrade() -> None:
    """Drop both tables (reviews first — FK to requests)."""
    op.drop_index("ix_config_change_reviews_request", table_name="config_change_reviews")
    op.drop_table("config_change_reviews")
    op.drop_index("ix_config_change_requests_tenant_status", table_name="config_change_requests")
    op.drop_table("config_change_requests")
