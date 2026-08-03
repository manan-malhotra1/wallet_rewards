"""reward_outbox durable trigger table + reward_events.seen_at column

Creates `reward_outbox` (a durable trigger written atomically with a rewardable
wallet transaction, FK to `transactions.id`, indexed on (tenant_id, status)) and
adds the nullable `reward_events.seen_at` TIMESTAMPTZ marking downstream pickup.

Revision ID: 0050
Revises: 0049
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create reward_outbox with its tenant/status index and add seen_at."""
    op.create_table(
        "reward_outbox",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_reward_outbox_tenant_status",
        "reward_outbox",
        ["tenant_id", "status"],
        unique=False,
    )
    op.add_column(
        "reward_events",
        sa.Column("seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop seen_at and the reward_outbox table (with its index)."""
    op.drop_column("reward_events", "seen_at")
    op.drop_index("idx_reward_outbox_tenant_status", table_name="reward_outbox")
    op.drop_table("reward_outbox")
