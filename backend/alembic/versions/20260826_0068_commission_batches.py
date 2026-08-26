"""Bulk commission disbursement / withdrawal batches.

Spec: docs/superpowers/specs/2026-08-26-commission-wallet-design.md §4.5-4.7.

Adds the batch header, its rows and its append-only review thread, and extends
ck_approval_policies_operation with the two new bulk operations.

Revision ID: 0068
Revises: 0067
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068"
down_revision: str | Sequence[str] | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OPS = (
    "operation IS NULL OR operation IN ('fund_user', 'withdraw_user', "
    "'adjust_system_wallet', 'create_bank_mirror')"
)
_NEW_OPS = (
    "operation IS NULL OR operation IN ('fund_user', 'withdraw_user', "
    "'adjust_system_wallet', 'create_bank_mirror', "
    "'commission_disbursement', 'commission_withdrawal')"
)


def upgrade() -> None:
    """Create the three batch tables and widen the approval-policy CHECK."""
    op.create_table(
        "commission_batches",
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
        sa.Column("batch_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("row_count_total", sa.Integer(), nullable=False),
        sa.Column("row_count_valid", sa.Integer(), nullable=False),
        sa.Column("amount_total", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "destination_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=True,
        ),
        sa.Column("created_by_admin_id", sa.String(100), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "batch_type IN ('disbursement', 'withdrawal')",
            name="ck_commission_batches_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPLIED', 'APPLIED_PARTIAL', 'REJECTED', 'WITHDRAWN')",
            name="ck_commission_batches_status",
        ),
        sa.CheckConstraint(
            "required_approvals IN (1, 2)",
            name="ck_commission_batches_required_approvals",
        ),
    )
    op.create_index("ix_commission_batches_tenant_id", "commission_batches", ["tenant_id"])
    op.create_index(
        "ix_commission_batches_tenant_status", "commission_batches", ["tenant_id", "status"]
    )

    op.create_table(
        "commission_batch_rows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("commission_batches.id"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("msisdn", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "resolved_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "resolved_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=True,
        ),
        sa.Column("balance_snapshot", sa.Numeric(20, 6), nullable=True),
        sa.Column("snapshot_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.String(100), nullable=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('valid', 'rejected', 'posted', 'failed')",
            name="ck_commission_batch_rows_status",
        ),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_commission_batch_rows_number"),
    )
    op.create_index("ix_commission_batch_rows_batch_id", "commission_batch_rows", ["batch_id"])
    op.create_index(
        "ix_commission_batch_rows_batch_status",
        "commission_batch_rows",
        ["batch_id", "status"],
    )

    op.create_table(
        "commission_batch_reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("commission_batches.id"),
            nullable=False,
        ),
        sa.Column("admin_id", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_commission_batch_reviews_decision",
        ),
        sa.UniqueConstraint(
            "batch_id", "admin_id", name="uq_commission_batch_reviews_approver"
        ),
    )
    op.create_index(
        "ix_commission_batch_reviews_batch_id", "commission_batch_reviews", ["batch_id"]
    )

    op.drop_constraint("ck_approval_policies_operation", "approval_policies", type_="check")
    op.create_check_constraint(
        "ck_approval_policies_operation", "approval_policies", _NEW_OPS
    )


def downgrade() -> None:
    """Drop the batch tables and restore the narrower approval-policy CHECK."""
    op.drop_constraint("ck_approval_policies_operation", "approval_policies", type_="check")
    op.create_check_constraint(
        "ck_approval_policies_operation", "approval_policies", _OLD_OPS
    )
    op.drop_table("commission_batch_reviews")
    op.drop_table("commission_batch_rows")
    op.drop_table("commission_batches")
