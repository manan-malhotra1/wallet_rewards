"""create user_operation_requests/reviews (admin user create/edit maker-checker)

Four-eyes maker-checker for administrator user-operations (create a user, edit an
existing user): a request table plus an append-only review thread. No data
backfill — the service defaults to 1 approval (four-eyes) when no policy applies.
Mirrors the money_operations tables (migration 0040).

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the two user-operation tables with constraints and indexes."""
    op.create_table(
        "user_operation_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("maker_admin_id", sa.String(length=255), nullable=False),
        sa.Column("required_approvals", sa.Integer(), server_default="1", nullable=False),
        sa.Column("applied_user_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "operation IN ('create_user', 'update_user')",
            name="ck_user_operation_requests_operation",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CHANGES_REQUESTED', 'APPLIED', 'WITHDRAWN')",
            name="ck_user_operation_requests_status",
        ),
        sa.CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_user_operation_requests_required_approvals",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_operation_requests_tenant_status",
        "user_operation_requests",
        ["tenant_id", "status"],
    )

    op.create_table(
        "user_operation_reviews",
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
        sa.CheckConstraint(
            "actor_role IN ('maker', 'checker')",
            name="ck_user_operation_reviews_actor_role",
        ),
        sa.CheckConstraint(
            "action IN ('submitted', 'approved', 'changes_requested', "
            "'revised', 'resubmitted', 'withdrawn', 'applied')",
            name="ck_user_operation_reviews_action",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["user_operation_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_operation_reviews_request",
        "user_operation_reviews",
        ["request_id", "created_at"],
    )


def downgrade() -> None:
    """Drop the two user-operation tables (and their indexes)."""
    op.drop_index("ix_user_operation_reviews_request", table_name="user_operation_reviews")
    op.drop_table("user_operation_reviews")
    op.drop_index(
        "ix_user_operation_requests_tenant_status",
        table_name="user_operation_requests",
    )
    op.drop_table("user_operation_requests")
