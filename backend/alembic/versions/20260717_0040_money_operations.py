"""create money_operation_requests/reviews + approval_policies (Epic 18 N-eyes)

N-eyes maker-checker for treasury + admin money movements: a request table, an
append-only review thread, and a per-tenant/per-operation approval policy. No
data backfill — the service defaults to 1 approval (two-eyes) when no policy row
matches.

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the three Epic 18 tables with constraints and indexes."""
    op.create_table(
        "money_operation_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("maker_admin_id", sa.String(length=255), nullable=False),
        sa.Column("required_approvals", sa.Integer(), server_default="1", nullable=False),
        sa.Column("applied_transaction_id", sa.UUID(), nullable=True),
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
            "operation IN ('fund_user', 'withdraw_user', "
            "'adjust_system_wallet', 'create_bank_mirror')",
            name="ck_money_operation_requests_operation",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CHANGES_REQUESTED', 'APPLIED', 'WITHDRAWN')",
            name="ck_money_operation_requests_status",
        ),
        sa.CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_money_operation_requests_required_approvals",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_money_operation_requests_tenant_status",
        "money_operation_requests",
        ["tenant_id", "status"],
    )

    op.create_table(
        "money_operation_reviews",
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
            name="ck_money_operation_reviews_actor_role",
        ),
        sa.CheckConstraint(
            "action IN ('submitted', 'approved', 'changes_requested', "
            "'revised', 'resubmitted', 'withdrawn', 'applied')",
            name="ck_money_operation_reviews_action",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["money_operation_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_money_operation_reviews_request",
        "money_operation_reviews",
        ["request_id", "created_at"],
    )

    op.create_table(
        "approval_policies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=True),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
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
            "operation IS NULL OR operation IN ('fund_user', 'withdraw_user', "
            "'adjust_system_wallet', 'create_bank_mirror')",
            name="ck_approval_policies_operation",
        ),
        sa.CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_approval_policies_required_approvals",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "operation", name="uq_approval_policies_tenant_operation"),
    )


def downgrade() -> None:
    """Drop the three Epic 18 tables (and their indexes)."""
    op.drop_table("approval_policies")
    op.drop_index("ix_money_operation_reviews_request", table_name="money_operation_reviews")
    op.drop_table("money_operation_reviews")
    op.drop_index(
        "ix_money_operation_requests_tenant_status",
        table_name="money_operation_requests",
    )
    op.drop_table("money_operation_requests")
