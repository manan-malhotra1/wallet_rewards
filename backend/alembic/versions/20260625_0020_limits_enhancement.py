"""extend limit_configs (weekly/monthly) + create wallet_limit_configs

Phase G enhancement (WAL-233). Adds rolling weekly + monthly count/value
caps to the service-wise `limit_configs`, and introduces
`wallet_limit_configs` — per-(tenant, currency) financial-wallet limits:
a max-balance ceiling plus cumulative send + receive count/value caps
across daily/weekly/monthly rolling windows.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add weekly/monthly caps to limit_configs + create wallet_limit_configs."""

    # --- 1. Extend limit_configs with weekly + monthly caps -----------------
    op.add_column("limit_configs", sa.Column("weekly_count_cap", sa.Integer(), nullable=True))
    op.add_column(
        "limit_configs",
        sa.Column("weekly_value_cap", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column("limit_configs", sa.Column("monthly_count_cap", sa.Integer(), nullable=True))
    op.add_column(
        "limit_configs",
        sa.Column("monthly_value_cap", sa.Numeric(20, 6), nullable=True),
    )

    # --- 2. wallet_limit_configs --------------------------------------------
    # Per-(tenant, currency) financial-wallet limits. Every cap is nullable
    # (NULL = no limit). currency is VARCHAR(10) to match the widened
    # currency columns (migration 0018).
    op.create_table(
        "wallet_limit_configs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("max_balance", sa.Numeric(20, 6), nullable=True),
        # Cumulative outbound (DEBIT) caps.
        sa.Column("send_daily_count_cap", sa.Integer(), nullable=True),
        sa.Column("send_daily_value_cap", sa.Numeric(20, 6), nullable=True),
        sa.Column("send_weekly_count_cap", sa.Integer(), nullable=True),
        sa.Column("send_weekly_value_cap", sa.Numeric(20, 6), nullable=True),
        sa.Column("send_monthly_count_cap", sa.Integer(), nullable=True),
        sa.Column("send_monthly_value_cap", sa.Numeric(20, 6), nullable=True),
        # Cumulative inbound (CREDIT) caps.
        sa.Column("receive_daily_count_cap", sa.Integer(), nullable=True),
        sa.Column("receive_daily_value_cap", sa.Numeric(20, 6), nullable=True),
        sa.Column("receive_weekly_count_cap", sa.Integer(), nullable=True),
        sa.Column("receive_weekly_value_cap", sa.Numeric(20, 6), nullable=True),
        sa.Column("receive_monthly_count_cap", sa.Integer(), nullable=True),
        sa.Column("receive_monthly_value_cap", sa.Numeric(20, 6), nullable=True),
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
        sa.UniqueConstraint(
            "tenant_id",
            "currency",
            name="uq_wallet_limit_configs_scope",
        ),
    )
    op.create_index(
        "ix_wallet_limit_configs_tenant_id",
        "wallet_limit_configs",
        ["tenant_id"],
    )


def downgrade() -> None:
    """Drop wallet_limit_configs + remove the weekly/monthly limit_configs caps."""
    op.drop_index("ix_wallet_limit_configs_tenant_id", table_name="wallet_limit_configs")
    op.drop_table("wallet_limit_configs")

    op.drop_column("limit_configs", "monthly_value_cap")
    op.drop_column("limit_configs", "monthly_count_cap")
    op.drop_column("limit_configs", "weekly_value_cap")
    op.drop_column("limit_configs", "weekly_count_cap")
