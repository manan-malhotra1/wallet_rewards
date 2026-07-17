"""create pin_changes (user self-service change-PIN, charged service)

A charged self-service change-PIN needs an idempotency + audit anchor
independent of the ledger: a zero-fee change moves no money (no transaction),
yet must still be replay-safe. `pin_changes` carries the per-tenant idempotency
key and the charge breakdown; `transaction_id` links to the fee transaction only
when a non-zero fee was posted. No PIN or hash is ever stored here (NFR-0170).

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the pin_changes table with its idempotency + FK constraints."""
    op.create_table(
        "pin_changes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fee_amount", sa.Numeric(precision=20, scale=6), server_default="0", nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=20, scale=6), server_default="0", nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="completed", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('completed')", name="ck_pin_changes_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_pin_changes_idempotency_per_tenant"
        ),
    )
    op.create_index("ix_pin_changes_tenant", "pin_changes", ["tenant_id"], unique=False)
    op.create_index("ix_pin_changes_user", "pin_changes", ["user_id"], unique=False)


def downgrade() -> None:
    """Drop the pin_changes table and its indexes."""
    op.drop_index("ix_pin_changes_user", table_name="pin_changes")
    op.drop_index("ix_pin_changes_tenant", table_name="pin_changes")
    op.drop_table("pin_changes")
