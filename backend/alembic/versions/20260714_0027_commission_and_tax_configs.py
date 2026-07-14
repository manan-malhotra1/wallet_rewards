"""create commission_configs + tax_configs (Pricing v2 Epic 19)

Story 19.3 — `commission_configs`: the platform-funded agent-commission
schedule, a structural twin of `pricing_configs` (amount bands + type-aware),
minus the `account_type` dimension.

Story 19.4 — `tax_configs`: jurisdiction-wide fee/commission tax rates + their
inclusive/exclusive flags, one row per (tenant, currency).

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_USER_TYPE_CHECK = "user_type IN ('consumer', 'agent', 'super_agent', 'merchant', 'head_merchant')"


def upgrade() -> None:
    """Create the commission_configs and tax_configs tables."""
    op.create_table(
        "commission_configs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("user_type", sa.String(length=20), nullable=True),
        sa.Column("amount_from", sa.Numeric(20, 6), nullable=True),
        sa.Column("amount_to", sa.Numeric(20, 6), nullable=True),
        sa.Column("fixed_commission", sa.Numeric(20, 6), server_default="0", nullable=False),
        sa.Column("variable_commission_pct", sa.Numeric(8, 6), server_default="0", nullable=False),
        sa.Column("commission_cap", sa.Numeric(20, 6), nullable=True),
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
        sa.CheckConstraint("fixed_commission >= 0", name="ck_commission_configs_fixed_nonneg"),
        sa.CheckConstraint(
            "variable_commission_pct >= 0 AND variable_commission_pct < 1",
            name="ck_commission_configs_variable_pct_range",
        ),
        sa.CheckConstraint(_USER_TYPE_CHECK, name="ck_commission_configs_user_type"),
        sa.CheckConstraint(
            "amount_from IS NULL OR amount_to IS NULL OR amount_to > amount_from",
            name="ck_commission_configs_amount_band",
        ),
    )
    op.create_index("ix_commission_configs_tenant_id", "commission_configs", ["tenant_id"])
    # NULLS NOT DISTINCT so two NULL-type/NULL-band rows for the same scope collide.
    op.execute(
        "ALTER TABLE commission_configs ADD CONSTRAINT uq_commission_configs_scope "
        "UNIQUE NULLS NOT DISTINCT "
        "(tenant_id, transaction_type, currency, user_type, amount_from)"
    )

    op.create_table(
        "tax_configs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("fee_tax_pct", sa.Numeric(8, 6), server_default="0", nullable=False),
        sa.Column("commission_tax_pct", sa.Numeric(8, 6), server_default="0", nullable=False),
        sa.Column(
            "fee_tax_inclusive", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "commission_tax_inclusive",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.UniqueConstraint("tenant_id", "currency", name="uq_tax_configs_scope"),
        sa.CheckConstraint(
            "fee_tax_pct >= 0 AND fee_tax_pct < 1", name="ck_tax_configs_fee_tax_pct_range"
        ),
        sa.CheckConstraint(
            "commission_tax_pct >= 0 AND commission_tax_pct < 1",
            name="ck_tax_configs_commission_tax_pct_range",
        ),
    )
    op.create_index("ix_tax_configs_tenant_id", "tax_configs", ["tenant_id"])


def downgrade() -> None:
    """Drop both tables."""
    op.drop_index("ix_tax_configs_tenant_id", table_name="tax_configs")
    op.drop_table("tax_configs")
    op.drop_index("ix_commission_configs_tenant_id", table_name="commission_configs")
    op.drop_table("commission_configs")
