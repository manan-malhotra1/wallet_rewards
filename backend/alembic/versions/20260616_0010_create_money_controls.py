"""create reward_budgets, limit_configs, pricing_configs (Phase G)

Phase G — Money Controls. Three new tables back budgets (WAL-50),
per-transaction limits (WAL-51), and the pricing engine (WAL-52). Plus
a CHECK-constraint update on accounts to recognise the new
`system_fee_collected` account type that pricing fees credit into.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the three control tables + extend accounts CHECK."""

    # --- 1. reward_budgets ---------------------------------------------------
    op.create_table(
        "reward_budgets",
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
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column(
            "scope_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("window_type", sa.String(20), nullable=False),
        sa.Column("cap_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
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
            "scope_type IN ('tenant', 'rule')",
            name="ck_reward_budgets_scope_type",
        ),
        sa.CheckConstraint(
            "window_type IN ('rolling_24h', 'rolling_7d', 'calendar_month', 'lifetime')",
            name="ck_reward_budgets_window_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused')",
            name="ck_reward_budgets_status",
        ),
        sa.CheckConstraint(
            "cap_amount > 0",
            name="ck_reward_budgets_cap_positive",
        ),
    )
    op.create_index("ix_reward_budgets_tenant_id", "reward_budgets", ["tenant_id"])
    # Partial unique indexes — Postgres treats NULL as distinct on plain
    # UNIQUE, so we split into two indexes (one per scope type).
    op.create_index(
        "uq_reward_budgets_tenant_scope",
        "reward_budgets",
        ["tenant_id", "currency", "window_type"],
        unique=True,
        postgresql_where="scope_id IS NULL",
    )
    op.create_index(
        "uq_reward_budgets_rule_scope",
        "reward_budgets",
        ["tenant_id", "scope_id", "currency", "window_type"],
        unique=True,
        postgresql_where="scope_id IS NOT NULL",
    )

    # --- 2. limit_configs ---------------------------------------------------
    op.create_table(
        "limit_configs",
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
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("min_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("max_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("daily_count_cap", sa.Integer(), nullable=True),
        sa.Column("daily_value_cap", sa.Numeric(20, 6), nullable=True),
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
            "transaction_type",
            "account_type",
            "currency",
            name="uq_limit_configs_scope",
        ),
    )
    op.create_index("ix_limit_configs_tenant_id", "limit_configs", ["tenant_id"])

    # --- 3. pricing_configs --------------------------------------------------
    op.create_table(
        "pricing_configs",
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
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column(
            "fixed_fee",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "variable_fee_pct",
            sa.Numeric(8, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("fee_cap", sa.Numeric(20, 6), nullable=True),
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
            "transaction_type",
            "account_type",
            "currency",
            name="uq_pricing_configs_scope",
        ),
        sa.CheckConstraint(
            "fixed_fee >= 0",
            name="ck_pricing_configs_fixed_fee_nonneg",
        ),
        sa.CheckConstraint(
            "variable_fee_pct >= 0 AND variable_fee_pct < 1",
            name="ck_pricing_configs_variable_fee_pct_range",
        ),
    )
    op.create_index("ix_pricing_configs_tenant_id", "pricing_configs", ["tenant_id"])

    # --- 4. Extend accounts.account_type CHECK ------------------------------
    # Add 'system_fee_collected' so pricing fees can credit a real account.
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        "account_type IN ("
        "'financial_wallet', "
        "'points_account', "
        "'system_points_issuance', "
        "'provider_redemption_wallet', "
        "'system_cash_inflow', "
        "'system_fee_collected'"
        ")",
    )


def downgrade() -> None:
    """Drop the three control tables + revert the accounts CHECK."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        "account_type IN ("
        "'financial_wallet', "
        "'points_account', "
        "'system_points_issuance', "
        "'provider_redemption_wallet', "
        "'system_cash_inflow'"
        ")",
    )

    op.drop_index("ix_pricing_configs_tenant_id", table_name="pricing_configs")
    op.drop_table("pricing_configs")

    op.drop_index("ix_limit_configs_tenant_id", table_name="limit_configs")
    op.drop_table("limit_configs")

    op.drop_index("uq_reward_budgets_rule_scope", table_name="reward_budgets")
    op.drop_index("uq_reward_budgets_tenant_scope", table_name="reward_budgets")
    op.drop_index("ix_reward_budgets_tenant_id", table_name="reward_budgets")
    op.drop_table("reward_budgets")
