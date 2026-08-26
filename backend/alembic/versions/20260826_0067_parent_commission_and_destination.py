"""Commission payout destination + parent commission terms.

Spec: docs/superpowers/specs/2026-08-26-commission-wallet-design.md §4.3, §4.4.

Every existing commission_configs row backfills to payout_destination =
'main_wallet' with zero parent terms, which is exactly today's behaviour — no
commission reprices on deploy (D18).

Revision ID: 0067
Revises: 0066
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the destination and parent-rate columns with today's behaviour as default."""
    op.add_column(
        "commission_configs",
        sa.Column(
            "payout_destination",
            sa.String(length=20),
            nullable=False,
            server_default="main_wallet",
        ),
    )
    op.add_column(
        "commission_configs",
        sa.Column(
            "parent_fixed_commission",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "commission_configs",
        sa.Column(
            "parent_variable_commission_pct",
            sa.Numeric(8, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "commission_configs",
        sa.Column("parent_commission_cap", sa.Numeric(20, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_commission_configs_payout_destination",
        "commission_configs",
        "payout_destination IN ('main_wallet', 'commission_wallet')",
    )
    op.create_check_constraint(
        "ck_commission_configs_parent_fixed_nonneg",
        "commission_configs",
        "parent_fixed_commission >= 0",
    )
    op.create_check_constraint(
        "ck_commission_configs_parent_variable_pct_range",
        "commission_configs",
        "parent_variable_commission_pct >= 0 AND parent_variable_commission_pct < 1",
    )
    op.add_column(
        "transactions",
        sa.Column(
            "parent_commission_amount",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Drop the parent-commission and destination columns."""
    op.drop_column("transactions", "parent_commission_amount")
    op.drop_constraint(
        "ck_commission_configs_parent_variable_pct_range", "commission_configs", type_="check"
    )
    op.drop_constraint(
        "ck_commission_configs_parent_fixed_nonneg", "commission_configs", type_="check"
    )
    op.drop_constraint(
        "ck_commission_configs_payout_destination", "commission_configs", type_="check"
    )
    op.drop_column("commission_configs", "parent_commission_cap")
    op.drop_column("commission_configs", "parent_variable_commission_pct")
    op.drop_column("commission_configs", "parent_fixed_commission")
    op.drop_column("commission_configs", "payout_destination")
